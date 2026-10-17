"""Majors graph, written in code.

Nodes are majors: one name each, plus the other names the same major goes by. Edges say how well
a strong program in one major serves a student who wants the other:
    1.0  the same major under another name (International Relations = Global Studies)
    0.8  very close (Neuroscience - Psychology)
    0.6  closely related, many shared courses (Physics - Engineering)
    0.4  related (Biology - Chemistry)
    0.2  loosely related: majors in the same family with no closer link
Any name (a college's program or a student's major) is placed on a node by its exact name first,
then by key words ("Mechanical Engineering" -> Engineering). Names that fit no node match nothing.

Each node also lists the school subjects that matter for it, used for "relevant coursework".
"""

import re

# node: (family, other names, relevant school subjects)
MAJORS = {
    # mathematics and computing
    "Mathematics": ("math", ["math", "maths", "applied mathematics", "pure mathematics", "computational mathematics",
                             "mathematics and statistics", "mathematics and computer science"], ["math"]),
    "Statistics and Data Science": ("math", ["statistics", "data science", "applied statistics", "data analytics",
                                             "business analytics", "financial analytics"], ["math", "computer science"]),
    "Computer Science": ("math", ["cs", "computing", "computer and information sciences", "artificial intelligence",
                                  "software engineering", "human computer interaction", "computational science"],
                         ["math", "computer science"]),
    "Information Technology": ("math", ["it", "information science", "information systems", "information science studies"],
                               ["computer science", "math"]),
    # physical sciences
    "Physics": ("physical", ["astrophysics", "astronomy", "applied physics", "theoretical and mathematical physics"],
                ["physics", "math"]),
    "Chemistry": ("physical", ["chemical sciences"], ["chemistry", "math"]),
    "Earth Sciences": ("physical", ["geology", "earth science", "geosciences", "geochemistry", "geology earth science",
                                    "earth and planetary sciences"], ["geography", "physics", "chemistry"]),
    # life sciences
    "Biology": ("life", ["biological sciences", "biology biological sciences", "molecular biology", "cell biology",
                         "human biology", "ecology and evolutionary biology", "evolutionary biology", "genetics",
                         "microbiology", "zoology", "botany", "computational biology"], ["biology", "chemistry"]),
    "Neuroscience": ("life", ["behavioral neuroscience", "neurobiology", "neurobiology and anatomy"],
                     ["biology", "chemistry", "psychology"]),
    "Biochemistry": ("life", ["biochemistry and molecular biology", "molecular biochemistry", "biophysics"],
                     ["chemistry", "biology"]),
    "Environmental Science": ("life", ["environmental studies", "sustainability", "sustainability studies",
                                       "environmental biology", "natural resources", "conservation"],
                              ["biology", "geography", "chemistry"]),
    "Agricultural Sciences": ("life", ["agriculture", "animal sciences", "food science", "nutrition", "nutrition sciences"],
                              ["biology", "chemistry"]),
    # health
    "Pre-Medicine": ("health", ["medicine", "pre med", "premed", "pre medicine", "biomedical sciences", "health sciences"],
                     ["biology", "chemistry"]),
    "Nursing": ("health", ["registered nursing"], ["biology", "chemistry"]),
    "Public Health": ("health", ["global health", "international health", "community health", "epidemiology"],
                      ["biology", "math"]),
    "Kinesiology and Physical Therapy": ("health", ["kinesiology", "exercise science", "physical therapy",
                                                    "sports medicine", "exercise physiology"], ["biology"]),
    # engineering
    "Engineering": ("engineering", ["mechanical engineering", "electrical engineering", "civil engineering",
                                    "chemical engineering", "biomedical engineering", "bioengineering",
                                    "aerospace engineering", "computer engineering", "materials engineering",
                                    "industrial engineering", "engineering science", "robotics"], ["math", "physics"]),
    "Architecture": ("engineering", ["pre architecture", "architectural studies"], ["math", "arts", "physics"]),
    # social sciences
    "Economics": ("social", ["econ", "econometrics", "mathematical economics", "political economy",
                             "international economics", "econometrics and quantitative economics",
                             "business economics", "managerial economics"], ["math", "economics"]),
    "Political Science": ("social", ["politics", "government", "political science and government"],
                          ["history", "government"]),
    "International Relations": ("social", ["ir", "global studies", "international affairs", "international studies",
                                           "international relations and affairs", "globalization studies",
                                           "international globalization studies", "diplomacy"],
                                ["history", "government", "geography"]),
    "Public Policy": ("social", ["public policy analysis", "policy studies", "public administration"],
                      ["government", "economics", "history"]),
    "Psychology": ("social", ["cognitive psychology", "clinical psychology", "developmental psychology",
                              "experimental psychology", "behavioral sciences", "biopsychology"],
                   ["psychology", "biology", "math"]),
    "Cognitive Science": ("social", [], ["psychology", "math", "computer science", "biology"]),
    "Anthropology and Sociology": ("social", ["sociology", "anthropology", "sociology and anthropology", "archaeology"],
                                   ["history", "geography", "literature"]),
    "Legal Studies": ("social", ["law", "pre law", "jurisprudence"], ["government", "history", "literature"]),
    "Criminal Justice": ("social", ["criminology"], ["government", "history"]),
    "Urban Studies and Geography": ("social", ["geography", "urban studies", "urban planning"], ["geography", "history"]),
    "Education": ("social", ["teaching", "early childhood education", "secondary education"], ["literature", "languages"]),
    # business
    "Business": ("business", ["business administration", "management", "marketing", "entrepreneurship",
                              "international business", "commerce", "business administration and management"],
                 ["math", "economics"]),
    "Accounting and Finance": ("business", ["accounting", "finance", "financial mathematics"], ["math", "economics"]),
    "Sports Management": ("business", ["sport management", "sport and fitness administration"], ["economics", "math"]),
    # humanities
    "History": ("humanities", ["american studies"], ["history", "literature"]),
    "Philosophy": ("humanities", ["ethics", "bioethics"], ["history", "literature"]),
    "Religious Studies": ("humanities", ["religion", "theology"], ["history", "literature"]),
    "English": ("humanities", ["english language and literature", "literature", "comparative literature",
                               "creative writing", "writing"], ["english", "literature"]),
    "Languages and Linguistics": ("humanities", ["linguistics", "languages", "modern languages", "classics", "spanish",
                                                 "french", "german", "chinese", "japanese"],
                                  ["languages", "english", "literature"]),
    "Area and Cultural Studies": ("humanities", ["east asian studies", "asian studies", "african studies",
                                                 "latin american studies", "slavic studies", "gender studies",
                                                 "women s studies", "cultural studies", "ethnic studies"],
                                  ["history", "languages", "literature"]),
    "Communications": ("humanities", ["communication", "journalism", "media studies", "mass communication",
                                      "public relations", "advertising", "digital media"],
                       ["english", "literature", "languages"]),
    # arts
    "Art": ("arts", ["fine arts", "studio art", "art history", "visual arts", "fine studio arts"], ["arts"]),
    "Design": ("arts", ["graphic design", "visual communication", "design and visual communications",
                        "industrial design"], ["arts"]),
    "Film and Photography": ("arts", ["film", "cinema", "film studies", "photography", "cinematography"],
                             ["arts", "literature"]),
    "Performing Arts": ("arts", ["theatre", "theater", "drama", "dance"], ["arts", "literature"]),
    "Music": ("arts", ["music performance", "jazz"], ["arts"]),
}

EDGES = [
    # mathematics and computing
    ("Mathematics", "Statistics and Data Science", 0.8), ("Mathematics", "Computer Science", 0.6),
    ("Mathematics", "Physics", 0.6), ("Mathematics", "Engineering", 0.6), ("Mathematics", "Economics", 0.4),
    ("Mathematics", "Accounting and Finance", 0.4), ("Mathematics", "Philosophy", 0.2),
    ("Statistics and Data Science", "Computer Science", 0.8), ("Statistics and Data Science", "Economics", 0.6),
    ("Statistics and Data Science", "Information Technology", 0.6), ("Statistics and Data Science", "Business", 0.4),
    ("Statistics and Data Science", "Public Health", 0.4),
    ("Computer Science", "Information Technology", 0.8), ("Computer Science", "Engineering", 0.6),
    ("Computer Science", "Physics", 0.4), ("Computer Science", "Cognitive Science", 0.4),
    ("Information Technology", "Business", 0.4), ("Information Technology", "Engineering", 0.4),
    # physical sciences
    ("Physics", "Engineering", 0.6), ("Physics", "Chemistry", 0.4), ("Physics", "Earth Sciences", 0.4),
    ("Physics", "Philosophy", 0.2),
    ("Chemistry", "Biochemistry", 0.8), ("Chemistry", "Biology", 0.4), ("Chemistry", "Engineering", 0.4),
    ("Chemistry", "Environmental Science", 0.4), ("Chemistry", "Pre-Medicine", 0.6),
    ("Earth Sciences", "Environmental Science", 0.6),
    # life sciences and health
    ("Biology", "Neuroscience", 0.8), ("Biology", "Biochemistry", 0.8), ("Biology", "Pre-Medicine", 0.8),
    ("Biology", "Environmental Science", 0.6), ("Biology", "Agricultural Sciences", 0.6),
    ("Biology", "Public Health", 0.6), ("Biology", "Nursing", 0.6), ("Biology", "Kinesiology and Physical Therapy", 0.4),
    ("Biology", "Psychology", 0.4),
    ("Neuroscience", "Psychology", 0.8), ("Neuroscience", "Cognitive Science", 0.8), ("Neuroscience", "Pre-Medicine", 0.6),
    ("Neuroscience", "Biochemistry", 0.6), ("Neuroscience", "Chemistry", 0.4),
    ("Biochemistry", "Pre-Medicine", 0.6),
    ("Environmental Science", "Agricultural Sciences", 0.6), ("Environmental Science", "Public Policy", 0.4),
    ("Environmental Science", "Urban Studies and Geography", 0.4),
    ("Pre-Medicine", "Nursing", 0.6), ("Pre-Medicine", "Public Health", 0.6), ("Pre-Medicine", "Psychology", 0.4),
    ("Pre-Medicine", "Kinesiology and Physical Therapy", 0.4),
    ("Public Health", "Nursing", 0.6), ("Public Health", "Public Policy", 0.6),
    ("Public Health", "Anthropology and Sociology", 0.4),
    ("Kinesiology and Physical Therapy", "Sports Management", 0.4), ("Kinesiology and Physical Therapy", "Nursing", 0.4),
    # engineering and design
    ("Engineering", "Architecture", 0.4), ("Architecture", "Art", 0.6), ("Architecture", "Design", 0.6),
    ("Architecture", "Urban Studies and Geography", 0.4),
    # social sciences
    ("Economics", "Business", 0.6), ("Economics", "Accounting and Finance", 0.6), ("Economics", "Public Policy", 0.6),
    ("Economics", "Political Science", 0.4), ("Economics", "International Relations", 0.4),
    ("Political Science", "International Relations", 0.8), ("Political Science", "Public Policy", 0.8),
    ("Political Science", "Legal Studies", 0.6), ("Political Science", "History", 0.4),
    ("Political Science", "Philosophy", 0.4), ("Political Science", "Criminal Justice", 0.4),
    ("Political Science", "Anthropology and Sociology", 0.4), ("Political Science", "Communications", 0.2),
    ("International Relations", "Public Policy", 0.6), ("International Relations", "Area and Cultural Studies", 0.6),
    ("International Relations", "History", 0.4), ("International Relations", "Languages and Linguistics", 0.4),
    ("International Relations", "Anthropology and Sociology", 0.4),
    ("Public Policy", "Legal Studies", 0.4), ("Public Policy", "Urban Studies and Geography", 0.4),
    ("Psychology", "Cognitive Science", 0.8), ("Psychology", "Anthropology and Sociology", 0.4),
    ("Psychology", "Education", 0.4), ("Psychology", "Philosophy", 0.2),
    ("Cognitive Science", "Philosophy", 0.4), ("Cognitive Science", "Languages and Linguistics", 0.4),
    ("Anthropology and Sociology", "History", 0.4), ("Anthropology and Sociology", "Area and Cultural Studies", 0.6),
    ("Anthropology and Sociology", "Criminal Justice", 0.4), ("Anthropology and Sociology", "Urban Studies and Geography", 0.4),
    ("Anthropology and Sociology", "Religious Studies", 0.4), ("Anthropology and Sociology", "Education", 0.4),
    ("Criminal Justice", "Legal Studies", 0.6), ("Legal Studies", "Philosophy", 0.4),
    # business
    ("Business", "Accounting and Finance", 0.8), ("Business", "Sports Management", 0.6), ("Business", "Communications", 0.4),
    # humanities and arts
    ("History", "Philosophy", 0.4), ("History", "Religious Studies", 0.4), ("History", "English", 0.4),
    ("History", "Area and Cultural Studies", 0.6),
    ("Philosophy", "Religious Studies", 0.6), ("Philosophy", "English", 0.2),
    ("Religious Studies", "Area and Cultural Studies", 0.4),
    ("English", "Communications", 0.6), ("English", "Languages and Linguistics", 0.4),
    ("English", "Film and Photography", 0.2), ("English", "Performing Arts", 0.2),
    ("Languages and Linguistics", "Area and Cultural Studies", 0.6),
    ("Communications", "Film and Photography", 0.6),
    ("Art", "Design", 0.8), ("Art", "Film and Photography", 0.4),
    ("Design", "Film and Photography", 0.4), ("Design", "Communications", 0.4), ("Design", "Computer Science", 0.2),
    ("Film and Photography", "Performing Arts", 0.4), ("Performing Arts", "Music", 0.6),
]
SAME_FAMILY = 0.2

# Key words for names that are not listed exactly; the first match wins.
KEYWORDS = [
    (r"engineer", "Engineering"), (r"neuro", "Neuroscience"), (r"biochem", "Biochemistry"),
    (r"comput|software|artificial intelligence|machine learning", "Computer Science"),
    (r"\bdata\b|statistic|analytics", "Statistics and Data Science"), (r"\bmath", "Mathematics"),
    (r"physic|astro", "Physics"), (r"chemi", "Chemistry"), (r"geolog|\bearth\b|geoscien|planetary", "Earth Sciences"),
    (r"environment|sustainab|ecolog|conservation", "Environmental Science"),
    (r"agricult|animal|\bfood\b|nutrition", "Agricultural Sciences"),
    (r"biolog|life science|genetic|zoolog|botan|microbio", "Biology"), (r"nurs", "Nursing"),
    (r"philosoph|ethic", "Philosophy"), (r"sociol|anthropol|archa?eolog", "Anthropology and Sociology"),
    (r"health|epidemiol", "Public Health"), (r"pre ?med|medic", "Pre-Medicine"),
    (r"kinesiol|exercise|physical therapy", "Kinesiology and Physical Therapy"), (r"sport", "Sports Management"),
    (r"architect", "Architecture"), (r"econom", "Economics"), (r"account|financ", "Accounting and Finance"),
    (r"communicat|journalis|\bmedia\b|public relations|advertis", "Communications"),
    (r"business|management|marketing|entrepreneur|commerce", "Business"),
    (r"international|global|diplomac", "International Relations"), (r"polic", "Public Policy"),
    (r"politic|government", "Political Science"), (r"cognitive", "Cognitive Science"), (r"psych", "Psychology"),
    (r"crimin", "Criminal Justice"),
    (r"\blaw\b|legal|juris", "Legal Studies"), (r"urban|geograph|planning", "Urban Studies and Geography"),
    (r"educat|teach", "Education"), (r"histor", "History"),
    (r"relig|theolog", "Religious Studies"),
    (r"linguist|language|spanish|french|german|chinese|japanese|classic|latin\b", "Languages and Linguistics"),
    (r"english|literat|writing|rhetoric", "English"),
    (r"film|cinema|photograph", "Film and Photography"), (r"theat|drama|dance|perform", "Performing Arts"),
    (r"music|jazz", "Music"), (r"design", "Design"), (r"\barts?\b", "Art"),
]
NO_NODE = re.compile(r"liberal arts|interdisciplinary|general studies|undeclared|undecided")


def normalise(name):
    key = re.sub(r"[^a-z0-9 ]", " ", (name or "").lower())
    return re.sub(r"\s+", " ", key).strip()


_ALIASES = {normalise(n): n for n in MAJORS}
_ALIASES.update({normalise(alias): n for n, (_, aliases, _) in MAJORS.items() for alias in aliases})
_EDGES = {}
for _a, _b, _w in EDGES:
    assert _a in MAJORS and _b in MAJORS, (_a, _b)
    _EDGES[(_a, _b)] = _EDGES[(_b, _a)] = _w


def node(name):
    """The graph node a major or program name belongs to, or None."""
    key = normalise(name)
    if not key or NO_NODE.search(key):
        return None
    if key in _ALIASES:
        return _ALIASES[key]
    return next((n for rx, n in KEYWORDS if re.search(rx, key)), None)


def similarity(a, b):
    """0-1: how well a strong program in `b` serves a student who wants `a` (symmetric)."""
    if normalise(a) and normalise(a) == normalise(b):
        return 1.0
    na, nb = node(a), node(b)
    if na is None or nb is None:
        return 0.0
    if na == nb:
        return 1.0
    if (na, nb) in _EDGES:
        return _EDGES[(na, nb)]
    return SAME_FAMILY if MAJORS[na][0] == MAJORS[nb][0] else 0.0


def neighbours(name, min_sim=0.2):
    """[(node, similarity)] for the node of `name`, closest first."""
    n = node(name)
    if n is None:
        return []
    out = [(m, similarity(n, m)) for m in MAJORS if m != n]
    return sorted([x for x in out if x[1] >= min_sim], key=lambda x: (-x[1], x[0]))


def relevant_subjects(name):
    """School subject groups that matter for a major (see sources/transcript.py), or []."""
    n = node(name)
    return MAJORS[n][2] if n else []
