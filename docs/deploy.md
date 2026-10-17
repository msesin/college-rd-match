# Deploying the dashboard on an Oracle Cloud Always Free instance

Written for sharing one instance with another project. Placeholders: `<ip>` is the instance's public IP,
`<user>` is `ubuntu` (Ubuntu image) or `opc` (Oracle Linux), `dashboard.example.com` is your address.
If you have no domain, use `<ip-with-dashes>.sslip.io` (for 129.146.10.20: `129-146-10-20.sslip.io`).
It resolves to your IP and works with automatic HTTPS.

## 0. Check what the instance already runs

```bash
ssh <user>@<ip>
sudo ss -ltnp | grep -E ':80 |:443 |:8001 '    # which programs use web ports
python3 --version                              # the project needs 3.12 or newer; if older, see step 2 (uv)
df -h /; free -h
```
- Nothing on 80/443: use **Caddy** (`deploy/Caddyfile`).
- nginx or Apache already there: add a second site with `deploy/nginx.conf.example` (two sites can share
  ports 80/443 when they have different addresses).
- Something already on 8001: change the port in `deploy/ugs.service` and the web server file.

## 1. Open ports 80 and 443 (two places; both are needed)

1. **Oracle console**: Networking, Virtual cloud networks, your VCN, the subnet's Security List (or Network Security
   Group): add Ingress rules, source `0.0.0.0/0`, TCP, destination ports `80` and `443`.
2. **On the instance** (Oracle images block them by default):
   - Ubuntu: first run `sudo iptables -L INPUT -n --line-numbers` and note the number of the `REJECT` line (usually 5).
     Insert the two rules **at that number** so they sit above it (a rule below `REJECT` is never reached):
     `sudo iptables -I INPUT 5 -p tcp -m state --state NEW --dport 80 -j ACCEPT`, the same for `443`, then check
     the list again and run `sudo netfilter-persistent save`.
   - Oracle Linux: `sudo firewall-cmd --permanent --add-service=http --add-service=https && sudo firewall-cmd --reload`.

Also make the public IP **reserved** (Oracle console: instance, attached VNIC, IPv4 addresses) so it doesn't change.

## 2. Install what's needed

```bash
sudo apt update && sudo apt install -y rsync curl                  # Oracle Linux: sudo dnf install -y rsync curl
# Python: if the server's python3 is older than 3.12 (Ubuntu 20.04 has 3.8), get a private current Python with uv.
# It installs into your home folder and does not touch the system Python or other projects.
curl -LsSf https://astral.sh/uv/install.sh | sh
source ~/.local/bin/env            # or log out and in again
uv python install 3.14
# Caddy (only if you chose Caddy):
sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https curl
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt update && sudo apt install -y caddy
```
**If the Caddy apt repository fails** (it returned `402 Payment Required` on 2026-10-10), remove it
(`sudo rm -f /etc/apt/sources.list.d/caddy-stable.list && sudo apt update`) and install the binary instead:
```bash
ARCH=$(dpkg --print-architecture)
curl -fsSL "https://caddyserver.com/api/download?os=linux&arch=$ARCH" -o caddy
sudo mv caddy /usr/local/bin/caddy && sudo chmod +x /usr/local/bin/caddy
sudo groupadd --system caddy
sudo useradd --system --gid caddy --create-home --home-dir /var/lib/caddy --shell /usr/sbin/nologin caddy
sudo mkdir -p /etc/caddy
```
and create `/etc/systemd/system/caddy.service` (Caddy docs: caddyserver.com/docs/running#manual-installation).
The first time, start it with `sudo systemctl enable --now caddy`.

## 3. Copy the project from your laptop

On your **laptop**, in the project folder. This sends the code and the data folder (database, CDS files, research files);
it leaves out your local virtualenv and your local `.env`.

```bash
rsync -avz --exclude .venv --exclude .env --exclude staticfiles --exclude __pycache__ --exclude .git \
  ./ <user>@<ip>:/home/<user>/ugs-rd-matching/
```
Add `-e "ssh -i /path/to/your-key"` if you log in with a key file.

## 4. Set up the app on the server

```bash
cd ~/ugs-rd-matching
uv venv --python 3.14 .venv        # if the server's python3 is already 3.12+, `python3 -m venv .venv` also works
uv pip install --python .venv/bin/python -r requirements.txt
cp .env.example .env
nano .env
```
In `.env` on the server:
```
DJANGO_SECRET_KEY=<a new long random string: python3 -c "import secrets; print(secrets.token_urlsafe(50))">
DJANGO_DEBUG=0
DJANGO_ALLOWED_HOSTS=dashboard.example.com
DJANGO_CSRF_TRUSTED_ORIGINS=https://dashboard.example.com
STUDENT_EMAIL_DOMAINS=<your organisation's email domain, e.g. yourorg.org: only these addresses can sign up>
GEMINI_API_KEY=<same as on your laptop>
GEMINI_MODEL=<same as on your laptop>
GEMINI_MODEL_PRO=gemini-3.1-pro-preview
ALLOW_STUDENT_DATA_TO_GEMINI=<1 only with a paid-tier key whose terms do not use inputs for training>
LLM_RPM=15
```
Then:
```bash
chmod 600 .env
.venv/bin/python manage.py migrate
.venv/bin/python manage.py collectstatic --noinput
.venv/bin/python manage.py createsuperuser          # your login on the server
```

## 5. Run it as a service

```bash
sudo cp deploy/ugs.service /etc/systemd/system/ugs.service      # edit User and paths first if needed
sudo systemctl daemon-reload && sudo systemctl enable --now ugs
sudo systemctl status ugs --no-pager                            # should say active (running)
curl -I http://127.0.0.1:8001/admin/login/                      # should say 200
```

## 6. Put HTTPS in front

**Caddy:** put your address in `deploy/Caddyfile`, then
`sudo cp deploy/Caddyfile /etc/caddy/Caddyfile && sudo systemctl reload caddy`.
**nginx:** follow the header of `deploy/nginx.conf.example` (including `certbot`).

Open `https://dashboard.example.com` and log in. If the browser says the certificate failed, the usual causes are
ports 80/443 not open in both places (step 1), or the address in the file not pointing to your IP.

**Certificate fails with "Timeout during connect"?** Test from your own computer:
`nc -vz -w 5 <ip> 80` and `nc -vz -w 5 <ip> 443`. A timeout means a firewall is blocking: either the rule is below
`REJECT` in iptables, or the Oracle console is missing the ingress rule (Destination Port Range 80 / 443, Source Port
Range empty) in the subnet's Security List or in a network security group on the instance.

## 7. Harden it (after HTTPS works)

- In `.env` add `DJANGO_HSTS_SECONDS=3600`, restart (`sudo systemctl restart ugs`); once everything works for a few
  days, raise it to `31536000`.
- Add other admins as in the login guide: Users, Add user, tick **Staff status**, no permissions.
- Daily backups: `crontab -e`, add `30 3 * * * /home/<user>/ugs-rd-matching/deploy/backup.sh`. Backups go to
  `~/ugs-backups` on the same machine, so also copy them off it now and then (`scp` to your laptop).
- Oracle can reclaim idle Always Free instances. Keep the backups somewhere else too.
- Public demo login (`demo`, password in README.md): run `create_sample_students` once, then reset it every hour so
  visitors' changes do not last: `crontab -e`, add
  `5 * * * * cd /home/<user>/ugs-rd-matching && .venv/bin/python manage.py create_sample_students --demo-only > /dev/null`.
  To turn the demo off: `create_sample_students --delete` (removes all sample students and the demo login).

## After go-live: the server is the master copy

Admins edit the dashboard on the server, so **the server's database is now the real one**. Do not copy the laptop's
`db.sqlite3` over it again. Run the import and generate commands **on the server** instead (they keep hand edits):

```bash
cd ~/ugs-rd-matching
.venv/bin/python manage.py build_profiles
```

## Updating the code later

On your laptop: the same `rsync` as in step 3, but add `--exclude data` so the database and files on the server stay.
On the server:
```bash
cd ~/ugs-rd-matching
uv pip install --python .venv/bin/python -r requirements.txt
.venv/bin/python manage.py migrate
.venv/bin/python manage.py collectstatic --noinput
sudo systemctl restart ugs
```

## Student portal on the server

Add to the server `.env` (see `.env.example`):
- `STUDENT_DATA_KEY`: the **same key as on your laptop** if you copy student data over, otherwise a new one.
  Keep a copy in a password manager.
- `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `DEFAULT_FROM_EMAIL`: an SMTP service for
  the sign-up emails. Without them, emails are only written to the log (`sudo journalctl -u ugs`).
Then `sudo systemctl restart ugs`. Test with your own address loaded on a sample student:
`python manage.py create_sample_students --email you@your-domain.org`, sign up at /register/, then delete the samples.

## Before student data goes in

- Move the database from SQLite to PostgreSQL (the project was built to allow it).
- Use full-disk encryption for the volume and restrict SSH to your key (`PasswordAuthentication no`).
- Give applicants their own interface and permissions; today every logged-in user can edit every cell.
