"""Controlled vocabularies: skills/technologies and Kazakhstan cities (DR-03, DR-05).

Alias syntax in the tables below:
    "python"      case-insensitive literal, matched on word boundaries
    "re:<regex>"  case-insensitive regular expression
    "cs:<lit>"    case-sensitive literal (e.g. "Excel" but not the verb "excel")
    "ctx:<lit>"   case-sensitive literal that also needs another technology nearby (e.g. "C", "R", "Go")
"""

from __future__ import annotations

import re
from dataclasses import dataclass

L = r"(?<![\w])"  # left word boundary (Unicode-aware)
R = r"(?![\w+#])"  # right boundary; also stops "C" matching inside "C++"/"C#"


@dataclass(frozen=True)
class Term:
    name: str
    pattern: re.Pattern[str]
    needs_context: bool
    literal: str | None  # for reverse lookup (profile input -> canonical name)


def _compile(name: str, alias: str) -> Term:
    if alias.startswith("re:"):
        return Term(name, re.compile(L + "(?:" + alias[3:] + ")" + R, re.I), False, None)
    if alias.startswith("cs:"):
        lit = alias[3:]
        return Term(name, re.compile(L + re.escape(lit) + R), False, lit.lower())
    if alias.startswith("ctx:"):
        lit = alias[4:]
        return Term(name, re.compile(r"(?<![\w+#./&-])" + re.escape(lit) + r"(?![\w+#&])"), True, None)
    return Term(name, re.compile(L + re.escape(alias) + R, re.I), False, alias.lower())


# --------------------------------------------------------------------------- skills

_SKILLS: list[tuple[str, list[str]]] = [
    ("Python", ["python", "питон"]),
    ("Java", ["java", "джава"]),
    ("JavaScript", ["javascript", r"re:(?<!\.)js", "ecmascript"]),  # not the "js" in "React.js"
    ("TypeScript", ["typescript"]),
    ("Go", ["golang", "ctx:Go"]),
    ("C++", ["c++", "cpp"]),
    ("C#", ["c#", "c sharp"]),
    ("C", ["ctx:C"]),
    ("Kotlin", ["kotlin"]),
    ("Swift", ["cs:Swift"]),
    ("PHP", ["php"]),
    ("Ruby", ["ruby"]),
    ("Rust", ["cs:Rust"]),
    ("Scala", ["scala"]),
    ("Dart", ["dart"]),
    ("R", ["ctx:R"]),
    ("SQL", ["sql"]),
    ("PostgreSQL", ["postgresql", "postgres", "постгрес"]),
    ("MySQL", ["mysql"]),
    ("MS SQL Server", ["ms sql", "mssql", "sql server", "t-sql"]),
    ("Oracle DB", ["oracle db", "oracle database", "pl/sql"]),
    ("MongoDB", ["mongodb", "mongo"]),
    ("Redis", ["redis"]),
    ("ClickHouse", ["clickhouse"]),
    ("Elasticsearch", ["elasticsearch"]),
    ("Docker", ["docker"]),
    ("Kubernetes", ["kubernetes", "k8s"]),
    ("Git", ["git", "github", "gitlab", "bitbucket"]),
    ("Linux", ["linux", "unix", "ubuntu"]),
    ("Bash", ["bash", "shell scripting"]),
    ("CI/CD", ["ci/cd", "jenkins", "github actions", "gitlab ci"]),
    ("AWS", ["aws", "amazon web services"]),
    ("Azure", ["azure"]),
    ("GCP", ["gcp", "google cloud"]),
    ("HTML", ["html", "html5"]),
    ("CSS", ["css", "css3", "scss", "sass", "tailwind"]),
    ("React", ["cs:React", "react.js", "reactjs"]),
    ("React Native", ["react native"]),
    ("Angular", ["angular"]),
    ("Vue.js", ["vue", "vue.js", "vuejs"]),
    ("Next.js", ["next.js", "nextjs"]),
    ("Node.js", ["node.js", "nodejs"]),
    ("Django", ["django"]),
    ("Flask", ["flask"]),
    ("FastAPI", ["fastapi"]),
    ("Spring", ["spring boot", "spring framework", "ctx:Spring"]),
    (".NET", [".net", "asp.net", "dotnet"]),
    ("Laravel", ["laravel"]),
    ("Flutter", ["flutter"]),
    ("Android", ["android"]),
    ("iOS", ["ios"]),
    ("REST API", ["rest api", "restful", "rest-api"]),
    ("GraphQL", ["graphql"]),
    ("Pandas", ["pandas"]),
    ("NumPy", ["numpy"]),
    ("scikit-learn", ["scikit-learn", "sklearn"]),
    ("TensorFlow", ["tensorflow"]),
    ("PyTorch", ["pytorch"]),
    ("Machine Learning", ["machine learning", r"re:машинн\w*\s+обучени\w*", "машиналық оқыту", "cs:ML"]),
    ("Deep Learning", ["deep learning", r"re:глубок\w*\s+обучени\w*"]),
    ("NLP", ["nlp", "natural language processing"]),
    ("Computer Vision", ["computer vision", r"re:компьютерн\w*\s+зрени\w*"]),
    ("Data Analysis", ["data analysis", "data analytics", r"re:анализ\w*\s+данн\w*", "деректерді талдау"]),
    ("Statistics", ["statistics", r"re:статистик\w*"]),
    ("Excel", ["cs:Excel", "ms excel", "эксель"]),
    ("Power BI", ["power bi", "powerbi"]),
    ("Tableau", ["tableau"]),
    ("Google Analytics", ["google analytics"]),
    ("1C", [r"re:1[сc](?::\s?предприятие)?"]),
    ("SAP", ["cs:SAP"]),
    ("Figma", ["figma"]),
    ("Photoshop", ["photoshop"]),
    ("Illustrator", ["illustrator"]),
    ("AutoCAD", ["autocad", "автокад"]),
    ("Revit", ["revit"]),
    ("MATLAB", ["matlab"]),
    ("Jira", ["jira"]),
    ("Postman", ["postman"]),
    ("Selenium", ["selenium"]),
    ("Kafka", ["kafka"]),
    ("Apache Spark", ["apache spark", "pyspark", "ctx:Spark"]),
    ("Airflow", ["airflow"]),
    ("Hadoop", ["hadoop"]),
    ("Agile/Scrum", ["agile", "scrum", "kanban"]),
    ("SMM", ["smm"]),
    ("SEO", ["seo"]),
    ("Copywriting", ["copywriting", "копирайтинг"]),
    ("IFRS", ["ifrs", "мсфо"]),
    ("Networking", ["tcp/ip", "ccna", r"re:компьютерн\w*\s+сет\w*"]),
]

SKILL_TERMS: list[Term] = [_compile(name, alias) for name, aliases in _SKILLS for alias in aliases]
SKILL_NAMES: list[str] = [name for name, _ in _SKILLS]

# --------------------------------------------------------------------------- cities

_KK_CASE = r"(?:да|де|та|те|ға|ге|қа|ке|дан|ден|тан|тен|нан|нен|ның|нің|дың|дің|тың|тің|ны|ні|ды|ді)?"

_CITIES: list[tuple[str, list[str]]] = [
    ("Almaty", [r"re:алмат\w*", r"re:алма-ат\w*", "almaty", "alma-ata"]),
    ("Astana", [r"re:астан\w*", r"re:нур-султан\w*", r"re:нұр-сұлтан\w*", "nur-sultan", "astana", r"re:целиноград\w*"]),
    ("Shymkent", [r"re:шымкент\w*", r"re:чимкент\w*", "shymkent"]),
    ("Karaganda", [r"re:караганд\w*", r"re:қарағанд\w*", "karaganda", "karagandy", "qaraghandy", "qaragandy"]),
    ("Aktobe", [r"re:актоб\w*", r"re:ақтөбе\w*", "aktobe", "aqtobe"]),
    ("Taraz", [r"re:тараз\w*", "taraz"]),
    ("Pavlodar", [r"re:павлодар\w*", "pavlodar"]),
    ("Oskemen", [r"re:усть-каменогорск\w*", r"re:өскемен\w*", r"re:оскемен\w*", "ust-kamenogorsk", "oskemen"]),
    ("Semey", [r"re:семе(?:й|я|е|ю|ем|й" + _KK_CASE + ")", r"re:семипалатинск\w*", "semey", "semei"]),
    ("Atyrau", [r"re:атырау\w*", "atyrau"]),
    ("Kostanay", [r"re:костана\w*", r"re:қостанай\w*", "kostanay", "qostanay"]),
    ("Kyzylorda", [r"re:кызылорд\w*", r"re:қызылорда\w*", "kyzylorda", "qyzylorda"]),
    ("Oral", [r"re:уральск\w*", r"re:орал" + _KK_CASE, "uralsk"]),  # Latin "Oral" clashes with English
    ("Petropavl", [r"re:петропавл\w*", r"re:petropavl\w*"]),
    ("Aktau", [r"re:актау\w*", r"re:ақтау\w*", "aktau", "aqtau"]),
    ("Turkistan", [r"re:туркестан\w*", r"re:түркістан\w*", "turkistan", "turkestan"]),
    ("Taldykorgan", [r"re:талдыкорган\w*", r"re:талдықорған\w*", "taldykorgan"]),
    ("Kokshetau", [r"re:кокшетау\w*", r"re:көкшетау\w*", "kokshetau"]),
    ("Ekibastuz", [r"re:экибастуз\w*", r"re:екібастұз\w*", "ekibastuz"]),
    ("Temirtau", [r"re:темиртау\w*", r"re:теміртау\w*", "temirtau"]),
    ("Zhezkazgan", [r"re:жезказган\w*", r"re:жезқазған\w*", "zhezkazgan"]),
    ("Konaev", [r"re:конаев\w*", r"re:қонаев\w*", r"re:капчага\w*", "konaev", "kapchagay"]),
]

CITY_TERMS: list[Term] = [_compile(name, alias) for name, aliases in _CITIES for alias in aliases]
CITY_NAMES: list[str] = [name for name, _ in _CITIES]


# --------------------------------------------------------------------------- normalisation of user input


def _normalize(value: str, terms: list[Term], names: list[str]) -> str | None:
    v = value.strip()
    if not v:
        return None
    for name in names:
        if name.lower() == v.lower():
            return name
    for term in terms:
        if term.literal is not None and term.literal == v.lower():
            return term.name
        if term.literal is None and not term.needs_context and term.pattern.fullmatch(v):
            return term.name
    return None


def normalize_skill(value: str) -> str | None:
    """Map 'postgres', 'Питон', 'react.js' ... to the canonical skill name; None if unknown."""
    return _normalize(value, SKILL_TERMS, SKILL_NAMES)


def normalize_city(value: str) -> str | None:
    """Map 'Нур-Султан', 'Алматы', 'Qaragandy' ... to the canonical city name; None if unknown."""
    return _normalize(value, CITY_TERMS, CITY_NAMES)
