#!/usr/bin/env python3
"""Generate realistic CV profiles (JSON + PDF) and job descriptions for E2E testing.

Usage:
    python generate_data.py [--cvs 210] [--jds 55] [--pdfs 50] [--seed 42]

Outputs:
    data/cvs.json   — array of CV profiles
    data/jds.json   — array of job descriptions
    data/pdfs/      — PDF files for extract API testing
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
from pathlib import Path

try:
    from fpdf import FPDF
except ImportError:
    print("fpdf2 is required: pip install fpdf2")
    sys.exit(1)

OUTPUT_DIR = Path(__file__).parent / "data"
FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONT_BOLD_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

# ────────────────────────────────────────────────────────────
# Name pools
# ────────────────────────────────────────────────────────────
FR_FIRST_M = [
    "Jean", "Pierre", "François", "Nicolas", "Thomas", "Laurent", "Philippe",
    "Antoine", "Olivier", "Julien", "Sébastien", "Alexandre", "Christophe",
    "Mathieu", "Guillaume", "Rémi", "Yann", "Hugo", "Benoît", "Étienne",
]
FR_FIRST_F = [
    "Marie", "Sophie", "Claire", "Isabelle", "Amélie", "Nathalie", "Catherine",
    "Valérie", "Sandrine", "Caroline", "Céline", "Aurélie", "Émilie", "Hélène",
    "Stéphanie", "Virginie", "Laure", "Camille", "Léa", "Manon",
]
FR_LAST = [
    "Dupont", "Martin", "Bernard", "Durand", "Moreau", "Lefebvre", "Leroy",
    "Roux", "David", "Bertrand", "Morel", "Fournier", "Girard", "Bonnet",
    "Lambert", "Fontaine", "Rousseau", "Vincent", "Muller", "Garnier",
]
EN_FIRST_M = [
    "James", "Michael", "David", "Robert", "William", "Christopher", "Daniel",
    "Andrew", "Matthew", "Richard", "Kevin", "Brian", "Mark", "Steven",
    "Jason", "Patrick", "Ryan", "Eric", "Nathan", "Scott",
]
EN_FIRST_F = [
    "Sarah", "Emily", "Jessica", "Jennifer", "Amanda", "Rachel", "Stephanie",
    "Michelle", "Lauren", "Nicole", "Katherine", "Megan", "Ashley", "Rebecca",
    "Victoria", "Olivia", "Hannah", "Samantha", "Elizabeth", "Christina",
]
EN_LAST = [
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Davis", "Miller",
    "Wilson", "Moore", "Taylor", "Anderson", "Thomas", "Jackson", "White",
    "Harris", "Martin", "Garcia", "Robinson", "Clark", "Lewis",
]
NA_FIRST_M = [
    "Ahmed", "Mohamed", "Karim", "Youcef", "Rachid", "Omar", "Djamel",
    "Mourad", "Amine", "Mehdi", "Samir", "Khaled", "Redouane", "Nassim",
    "Walid", "Sofiane", "Bilal", "Farid", "Lamine", "Hamza",
]
NA_FIRST_F = [
    "Fatima", "Amina", "Samira", "Leila", "Nadia", "Khadija", "Houria",
    "Meriem", "Yasmine", "Salima", "Djamila", "Farida", "Aicha", "Rania",
    "Sara", "Ines", "Lina", "Imane", "Sihem", "Nawal",
]
NA_LAST = [
    "Khebab", "Benmoussa", "Belkacem", "Boudjema", "Hamidi", "Zerrouki",
    "Benali", "Saidi", "Mebarki", "Boukhalfa", "Khelifi", "Rahmani",
    "Bouzid", "Mansouri", "Ait Ahmed", "Djerba", "Touati", "Ouali",
    "Charef", "Mokrani",
]

FR_LOCATIONS = [
    "Paris, France", "Lyon, France", "Marseille, France", "Toulouse, France",
    "Bordeaux, France", "Nantes, France", "Lille, France", "Strasbourg, France",
    "Montpellier, France", "Rennes, France", "Grenoble, France", "Nice, France",
]
EN_LOCATIONS = [
    "London, UK", "New York, USA", "San Francisco, USA", "Toronto, Canada",
    "Sydney, Australia", "Berlin, Germany", "Amsterdam, Netherlands",
    "Dublin, Ireland", "Singapore", "Dubai, UAE", "Boston, USA", "Chicago, USA",
]
NA_LOCATIONS = [
    "Alger, Algérie", "Oran, Algérie", "Constantine, Algérie",
    "Casablanca, Maroc", "Tunis, Tunisie", "Annaba, Algérie",
]

# ────────────────────────────────────────────────────────────
# Department configurations
# ────────────────────────────────────────────────────────────
DEPARTMENTS: dict[str, dict] = {
    "software_engineering": {
        "titles_en": [
            "Software Engineer", "Senior Software Developer", "Full Stack Developer",
            "Backend Engineer", "Frontend Developer", "Software Architect",
            "Lead Developer", "Principal Engineer",
        ],
        "titles_fr": [
            "Ingénieur Logiciel", "Développeur Full Stack Senior", "Développeur Backend",
            "Architecte Logiciel", "Développeur Frontend", "Lead Développeur",
            "Ingénieur d'Études et Développement", "Chef de Projet Technique",
        ],
        "skills": [
            "Python", "Java", "JavaScript", "TypeScript", "React", "Node.js",
            "PostgreSQL", "MongoDB", "Docker", "Kubernetes", "Git", "CI/CD",
            "REST API", "GraphQL", "AWS", "Azure", "Microservices", "Redis",
            "Go", "Rust", "C#", ".NET", "Spring Boot", "Django", "FastAPI",
            "Vue.js", "Angular", "HTML/CSS", "Agile/Scrum", "TDD",
        ],
        "companies_en": [
            "TechFlow Inc.", "CloudScale Solutions", "DataBridge Corp",
            "NexGen Software", "ByteWorks Ltd", "Quantum Dev",
        ],
        "companies_fr": [
            "Capgemini", "Sopra Steria", "Atos", "Thales Digital",
            "CGI France", "Alten", "Altran", "Devoteam",
        ],
        "certs": [
            "AWS Solutions Architect", "Azure Developer Associate",
            "Kubernetes Administrator (CKA)", "Google Cloud Professional",
            "Scrum Master (PSM I)", "Oracle Certified Java Developer",
        ],
        "edu_fields_en": ["Computer Science", "Software Engineering", "Information Technology"],
        "edu_fields_fr": ["Informatique", "Génie Logiciel", "Systèmes d'Information"],
    },
    "data_science": {
        "titles_en": [
            "Data Scientist", "Senior Data Analyst", "Machine Learning Engineer",
            "AI Research Scientist", "Data Engineer", "Analytics Manager",
            "Deep Learning Engineer", "NLP Engineer",
        ],
        "titles_fr": [
            "Data Scientist", "Ingénieur Machine Learning", "Analyste Données Senior",
            "Ingénieur IA", "Data Engineer", "Responsable Analytics",
            "Ingénieur Deep Learning", "Chercheur en IA",
        ],
        "skills": [
            "Python", "R", "SQL", "TensorFlow", "PyTorch", "Scikit-learn",
            "Pandas", "NumPy", "Spark", "Hadoop", "Tableau", "Power BI",
            "Statistics", "Machine Learning", "Deep Learning", "NLP",
            "Computer Vision", "A/B Testing", "Feature Engineering",
            "XGBoost", "LightGBM", "Keras", "MLflow", "Airflow",
            "BigQuery", "Databricks", "Snowflake", "dbt", "Looker",
        ],
        "companies_en": [
            "DataMinds Analytics", "AI Frontier Labs", "InsightPro",
            "QuantumML Corp", "NeuralPath Inc.", "DeepSense AI",
        ],
        "companies_fr": [
            "Dataiku", "OVHcloud", "Criteo", "ContentSquare",
            "Doctolib", "Meero", "Shift Technology", "Datadog",
        ],
        "certs": [
            "Google Professional Data Engineer", "AWS Machine Learning Specialty",
            "TensorFlow Developer Certificate", "Databricks Certified",
            "Microsoft Azure Data Scientist", "IBM Data Science Professional",
        ],
        "edu_fields_en": ["Data Science", "Statistics", "Applied Mathematics", "Computer Science"],
        "edu_fields_fr": ["Science des Données", "Statistiques", "Mathématiques Appliquées"],
    },
    "cybersecurity": {
        "titles_en": [
            "Security Engineer", "Cybersecurity Analyst", "Penetration Tester",
            "SOC Analyst", "Security Architect", "CISO", "Threat Intelligence Analyst",
            "Cloud Security Engineer",
        ],
        "titles_fr": [
            "Ingénieur Sécurité", "Analyste Cybersécurité", "Pentester",
            "Analyste SOC", "Architecte Sécurité", "RSSI",
            "Consultant Sécurité", "Ingénieur Sécurité Cloud",
        ],
        "skills": [
            "SIEM", "Splunk", "Wireshark", "Metasploit", "Nmap", "Burp Suite",
            "Firewall Management", "IDS/IPS", "Incident Response", "OSINT",
            "Threat Modeling", "Vulnerability Assessment", "ISO 27001",
            "NIST Framework", "SOC Operations", "Malware Analysis",
            "Network Security", "Cloud Security", "IAM", "Zero Trust",
            "Forensics", "OWASP", "PKI", "Endpoint Detection",
        ],
        "companies_en": [
            "CyberShield Corp", "SecureNet Solutions", "ThreatGuard Inc.",
            "InfoSec Global", "DefensePoint Ltd", "CipherTech",
        ],
        "companies_fr": [
            "Thales Cybersecurity", "Airbus CyberSecurity", "Orange Cyberdefense",
            "Wavestone", "Sogeti", "Stormshield",
        ],
        "certs": [
            "CISSP", "CEH (Certified Ethical Hacker)", "CompTIA Security+",
            "OSCP", "CISM", "GIAC GSEC", "ISO 27001 Lead Auditor",
        ],
        "edu_fields_en": ["Cybersecurity", "Computer Science", "Network Security"],
        "edu_fields_fr": ["Cybersécurité", "Sécurité Informatique", "Réseaux et Sécurité"],
    },
    "devops": {
        "titles_en": [
            "DevOps Engineer", "Site Reliability Engineer", "Platform Engineer",
            "Cloud Engineer", "Infrastructure Engineer", "Release Manager",
            "Senior DevOps Engineer", "Cloud Architect",
        ],
        "titles_fr": [
            "Ingénieur DevOps", "Ingénieur SRE", "Ingénieur Cloud",
            "Architecte Cloud", "Ingénieur Infrastructure",
            "Ingénieur Plateforme", "DevOps Senior", "Administrateur Système",
        ],
        "skills": [
            "Docker", "Kubernetes", "Terraform", "Ansible", "Jenkins",
            "GitLab CI", "GitHub Actions", "AWS", "GCP", "Azure",
            "Linux", "Prometheus", "Grafana", "ELK Stack", "Nginx",
            "Helm", "ArgoCD", "Vault", "Consul", "Istio",
            "Python", "Bash", "Go", "CloudFormation", "Pulumi",
        ],
        "companies_en": [
            "CloudOps Inc.", "InfraScale Solutions", "PlatformNow",
            "ReliabilityFirst Ltd", "AutoDeploy Corp", "ScaleForce",
        ],
        "companies_fr": [
            "OVHcloud", "Scaleway", "Clever Cloud", "Société Générale IT",
            "BNP Paribas IT", "Amadeus", "Dassault Systèmes",
        ],
        "certs": [
            "AWS Solutions Architect Professional", "CKA (Kubernetes Admin)",
            "HashiCorp Terraform Associate", "Google Cloud Architect",
            "Azure DevOps Engineer Expert", "Linux Foundation Certified",
        ],
        "edu_fields_en": ["Computer Science", "Systems Engineering", "Cloud Computing"],
        "edu_fields_fr": ["Informatique", "Systèmes et Réseaux", "Cloud Computing"],
    },
    "finance": {
        "titles_en": [
            "Financial Analyst", "Senior Accountant", "Finance Manager",
            "Controller", "Treasury Analyst", "Risk Analyst",
            "Investment Analyst", "Audit Manager",
        ],
        "titles_fr": [
            "Analyste Financier", "Comptable Senior", "Responsable Financier",
            "Contrôleur de Gestion", "Trésorier", "Analyste Risques",
            "Auditeur Interne", "Directeur Administratif et Financier",
        ],
        "skills": [
            "Financial Modeling", "Excel Advanced", "SAP FI/CO", "Bloomberg",
            "IFRS", "US GAAP", "Budgeting", "Forecasting", "Cash Flow",
            "Consolidation", "Audit", "Tax Compliance", "Risk Management",
            "Power BI", "Tableau", "VBA", "SQL", "Oracle Financials",
            "ERP Systems", "M&A Due Diligence", "Variance Analysis",
        ],
        "companies_en": [
            "Morgan & Associates", "Sterling Financial Group", "PrimeVest Capital",
            "Atlas Advisory", "Meridian Finance", "Apex Consulting",
        ],
        "companies_fr": [
            "BNP Paribas", "Société Générale", "AXA", "Crédit Agricole",
            "KPMG France", "Deloitte France", "PwC France", "EY France",
        ],
        "certs": [
            "CFA (Chartered Financial Analyst)", "CPA", "ACCA",
            "FRM (Financial Risk Manager)", "CIA (Certified Internal Auditor)",
            "DSCG", "DEC",
        ],
        "edu_fields_en": ["Finance", "Accounting", "Business Administration", "Economics"],
        "edu_fields_fr": ["Finance", "Comptabilité", "Gestion", "Économie"],
    },
    "human_resources": {
        "titles_en": [
            "HR Manager", "Talent Acquisition Specialist", "HR Business Partner",
            "Compensation & Benefits Analyst", "People Operations Manager",
            "Learning & Development Manager", "Recruiter", "HRIS Analyst",
        ],
        "titles_fr": [
            "Responsable RH", "Chargé de Recrutement", "HR Business Partner",
            "Responsable Formation", "Gestionnaire Paie",
            "Directeur des Ressources Humaines", "Chargé de Développement RH",
            "Responsable Relations Sociales",
        ],
        "skills": [
            "Talent Acquisition", "Employee Relations", "HRIS", "Workday",
            "SAP SuccessFactors", "Compensation & Benefits", "Performance Management",
            "Labor Law", "Change Management", "Organizational Development",
            "Diversity & Inclusion", "Payroll", "Onboarding", "Training",
            "Employee Engagement", "Workforce Planning", "HR Analytics",
        ],
        "companies_en": [
            "PeopleFirst Corp", "TalentBridge Inc.", "HRFlow Solutions",
            "WorkForce Dynamics", "CultureSync Ltd", "EngageHR",
        ],
        "companies_fr": [
            "Adecco France", "Randstad France", "ManpowerGroup France",
            "PageGroup France", "Robert Half France", "Hays France",
        ],
        "certs": [
            "SHRM-CP", "SHRM-SCP", "PHR", "SPHR",
            "CIPD Level 5", "HR Analytics Certificate",
        ],
        "edu_fields_en": ["Human Resources", "Organizational Psychology", "Business Administration"],
        "edu_fields_fr": ["Ressources Humaines", "Psychologie du Travail", "Management"],
    },
    "marketing": {
        "titles_en": [
            "Marketing Manager", "Digital Marketing Specialist", "Content Strategist",
            "SEO/SEM Manager", "Brand Manager", "Growth Hacker",
            "Product Marketing Manager", "Social Media Manager",
        ],
        "titles_fr": [
            "Responsable Marketing", "Chef de Projet Digital", "Responsable Communication",
            "Chargé de Marketing Digital", "Brand Manager",
            "Responsable Acquisition", "Content Manager", "Community Manager",
        ],
        "skills": [
            "Google Analytics", "Google Ads", "Facebook Ads", "SEO", "SEM",
            "Content Marketing", "Email Marketing", "CRM", "HubSpot",
            "Salesforce Marketing Cloud", "Social Media", "Brand Strategy",
            "A/B Testing", "Marketing Automation", "Copywriting",
            "Adobe Creative Suite", "Figma", "WordPress", "Mailchimp",
        ],
        "companies_en": [
            "BrandSpark Agency", "GrowthLab Inc.", "DigitalEdge Marketing",
            "ContentPro Solutions", "MediaFlow Corp", "AdVantage Group",
        ],
        "companies_fr": [
            "Publicis Groupe", "Havas", "AccorHotels Marketing",
            "L'Oréal Digital", "LVMH Digital", "Decathlon France",
        ],
        "certs": [
            "Google Analytics Certified", "Google Ads Certified",
            "HubSpot Inbound Marketing", "Facebook Blueprint",
            "Hootsuite Social Marketing", "Content Marketing Institute",
        ],
        "edu_fields_en": ["Marketing", "Communications", "Business Administration"],
        "edu_fields_fr": ["Marketing", "Communication", "Commerce"],
    },
    "sales": {
        "titles_en": [
            "Sales Manager", "Account Executive", "Business Development Manager",
            "Key Account Manager", "Sales Director", "Inside Sales Representative",
            "Enterprise Sales Executive", "Channel Partner Manager",
        ],
        "titles_fr": [
            "Responsable Commercial", "Ingénieur Commercial", "Directeur des Ventes",
            "Key Account Manager", "Business Developer",
            "Chef des Ventes", "Responsable Grands Comptes", "Attaché Commercial",
        ],
        "skills": [
            "Salesforce", "CRM", "B2B Sales", "B2C Sales", "Negotiation",
            "Pipeline Management", "Forecasting", "Cold Calling", "Lead Generation",
            "Account Management", "Consultative Selling", "MEDDIC",
            "SPIN Selling", "Contract Negotiation", "Revenue Forecasting",
            "Territory Management", "Partner Management", "Pricing Strategy",
        ],
        "companies_en": [
            "SalesForce Solutions", "RevenueMax Inc.", "CloseDeal Corp",
            "PipelinePro Ltd", "GrowthAccel", "DealMaker Group",
        ],
        "companies_fr": [
            "Bouygues Telecom", "SFR Business", "Dassault Systèmes",
            "Schneider Electric", "Saint-Gobain", "Michelin",
        ],
        "certs": [
            "Salesforce Administrator", "HubSpot Sales Certification",
            "Sandler Sales Training", "Miller Heiman Strategic Selling",
            "Challenger Sale Certified", "MEDDIC Certified",
        ],
        "edu_fields_en": ["Business", "Sales Management", "Marketing"],
        "edu_fields_fr": ["Commerce", "Management Commercial", "Marketing"],
    },
    "project_management": {
        "titles_en": [
            "Project Manager", "Senior Program Manager", "Scrum Master",
            "Agile Coach", "PMO Director", "Technical Project Manager",
            "Delivery Manager", "Product Owner",
        ],
        "titles_fr": [
            "Chef de Projet", "Directeur de Programme", "Scrum Master",
            "Coach Agile", "Responsable PMO", "Chef de Projet Technique",
            "Delivery Manager", "Product Owner",
        ],
        "skills": [
            "PMP", "Agile/Scrum", "Kanban", "Jira", "Confluence", "MS Project",
            "Risk Management", "Stakeholder Management", "Budgeting",
            "Resource Planning", "SAFe", "Prince2", "Waterfall",
            "Change Management", "Vendor Management", "RAID Log",
            "Earned Value Management", "Gantt Charts", "Sprint Planning",
        ],
        "companies_en": [
            "ProjectFlow Inc.", "AgilePath Solutions", "DeliverX Corp",
            "MethodWorks Ltd", "TransformNow", "PlanForward Group",
        ],
        "companies_fr": [
            "Capgemini Consulting", "Accenture France", "McKinsey France",
            "BCG France", "Sopra Steria Consulting", "Bearing Point",
        ],
        "certs": [
            "PMP (Project Management Professional)", "Prince2 Practitioner",
            "Certified Scrum Master (CSM)", "SAFe Agilist",
            "PMI-ACP", "ITIL Foundation",
        ],
        "edu_fields_en": ["Project Management", "Business Administration", "Engineering"],
        "edu_fields_fr": ["Management de Projet", "Gestion", "Ingénierie"],
    },
    "engineering": {
        "titles_en": [
            "Civil Engineer", "Mechanical Engineer", "Electrical Engineer",
            "Structural Engineer", "Process Engineer", "Quality Engineer",
            "Industrial Engineer", "Environmental Engineer",
        ],
        "titles_fr": [
            "Ingénieur Génie Civil", "Ingénieur Mécanique", "Ingénieur Électrique",
            "Ingénieur Structure", "Ingénieur Procédés", "Ingénieur Qualité",
            "Ingénieur Industriel", "Ingénieur Environnement",
        ],
        "skills": [
            "AutoCAD", "SolidWorks", "CATIA", "Revit", "MATLAB",
            "Finite Element Analysis", "Project Management", "ISO 9001",
            "Lean Manufacturing", "Six Sigma", "3D Modeling", "BIM",
            "HVAC Design", "Structural Analysis", "Process Optimization",
            "Quality Control", "Root Cause Analysis", "FMEA",
            "Technical Drawing", "Simulation",
        ],
        "companies_en": [
            "BuildTech Engineering", "StructuralPro Corp", "MechaFlow Inc.",
            "GreenBuild Solutions", "InfraPlan Ltd", "DesignCore Engineering",
        ],
        "companies_fr": [
            "Bouygues Construction", "Vinci", "Eiffage", "Colas",
            "Egis", "Artelia", "Setec", "Systra",
        ],
        "certs": [
            "Professional Engineer (PE)", "Lean Six Sigma Green Belt",
            "PMP", "LEED Accredited Professional", "ISO 9001 Lead Auditor",
            "Autodesk Certified Professional",
        ],
        "edu_fields_en": [
            "Civil Engineering", "Mechanical Engineering", "Electrical Engineering",
            "Industrial Engineering",
        ],
        "edu_fields_fr": [
            "Génie Civil", "Génie Mécanique", "Génie Électrique",
            "Génie Industriel",
        ],
    },
}

UNIVERSITIES_EN = [
    "MIT", "Stanford University", "University of Cambridge",
    "University of Toronto", "Imperial College London",
    "ETH Zurich", "University of Melbourne", "UC Berkeley",
    "Georgia Tech", "University of Michigan", "Columbia University",
    "Carnegie Mellon University", "University of Edinburgh",
    "University of Waterloo", "King's College London",
]
UNIVERSITIES_FR = [
    "École Polytechnique", "CentraleSupélec", "INSA Lyon",
    "Université Paris-Saclay", "HEC Paris", "ESSEC",
    "Sciences Po Paris", "Université de Strasbourg",
    "Télécom Paris", "ENSTA Paris", "Mines ParisTech",
    "Université Lyon 1", "Université de Bordeaux",
    "Université Grenoble Alpes", "ENSAE Paris",
]
UNIVERSITIES_NA = [
    "ESI (École nationale Supérieure d'Informatique)",
    "USTHB Alger", "Université de Constantine",
    "Université d'Oran", "ENSIA Alger",
    "Université de Annaba", "INELEC Boumerdès",
    "Université Mohammed V Rabat", "ENSA Casablanca",
]

DEGREES_EN = ["Bachelor's", "Master's", "MBA", "Ph.D."]
DEGREES_FR = ["Licence", "Master", "Ingénieur", "Doctorat", "MBA"]

LANGUAGE_LEVELS = ["native", "fluent", "advanced", "intermediate", "beginner"]

ACHIEVEMENT_VERBS_EN = [
    "Designed and implemented", "Led the migration of", "Built",
    "Developed", "Launched", "Optimized", "Automated",
    "Architected", "Delivered", "Spearheaded",
]
ACHIEVEMENT_VERBS_FR = [
    "Conception et mise en œuvre de", "Migration de", "Développement de",
    "Lancement de", "Optimisation de", "Automatisation de",
    "Architecture de", "Livraison de", "Pilotage de",
]
ACHIEVEMENT_OBJECTS_EN = [
    "a real-time data pipeline processing 2M events/day",
    "the company-wide ERP migration to cloud",
    "an automated CI/CD pipeline reducing deploy time by 70%",
    "a customer-facing dashboard used by 10K+ users",
    "a microservices architecture serving 50K RPM",
    "a machine learning model improving prediction accuracy by 25%",
    "a fraud detection system saving $2M annually",
    "a cross-functional training program for 200+ employees",
    "a cost optimization initiative reducing cloud spend by 40%",
    "a mobile application with 100K+ downloads",
]
ACHIEVEMENT_OBJECTS_FR = [
    "un pipeline de données temps réel traitant 2M événements/jour",
    "la migration ERP vers le cloud pour toute l'entreprise",
    "un pipeline CI/CD automatisé réduisant le temps de déploiement de 70%",
    "un tableau de bord client utilisé par 10K+ utilisateurs",
    "une architecture microservices supportant 50K RPM",
    "un modèle de machine learning améliorant la précision de 25%",
    "un système de détection de fraude économisant 2M€ par an",
    "un programme de formation transverse pour 200+ employés",
    "une initiative d'optimisation des coûts cloud réduisant les dépenses de 40%",
    "une application mobile avec 100K+ téléchargements",
]

SUMMARIES_EN = [
    "Experienced {title} with {years}+ years of expertise in {field}. Proven track record of delivering high-impact projects in fast-paced environments. Strong problem-solving skills and a passion for continuous learning.",
    "Results-driven {title} with {years} years of professional experience. Skilled in {skill1}, {skill2}, and {skill3}. Adept at collaborating with cross-functional teams to achieve business objectives.",
    "Dedicated {title} with a solid background spanning {years} years. Expertise in {field} with a focus on innovation and operational excellence. Committed to driving measurable results.",
    "Dynamic {title} bringing {years} years of hands-on experience. Specialized in {skill1} and {skill2}, with a strong analytical mindset. Proven ability to lead teams and manage complex projects.",
]
SUMMARIES_FR = [
    "{title} expérimenté(e) avec {years}+ années d'expertise en {field}. Bilan prouvé de livraison de projets à fort impact dans des environnements exigeants. Forte capacité de résolution de problèmes.",
    "Professionnel(le) orienté(e) résultats avec {years} ans d'expérience en tant que {title}. Compétences en {skill1}, {skill2} et {skill3}. Aptitude à collaborer avec des équipes pluridisciplinaires.",
    "{title} passionné(e) avec {years} ans d'expérience solide. Expertise en {field} avec un focus sur l'innovation et l'excellence opérationnelle.",
    "{title} dynamique avec {years} ans d'expérience pratique. Spécialisé(e) en {skill1} et {skill2}, avec un esprit analytique. Capacité prouvée à diriger des équipes.",
]

EMAIL_DOMAINS = [
    "gmail.com", "outlook.com", "yahoo.com", "protonmail.com",
    "live.fr", "hotmail.fr", "orange.fr", "free.fr",
]


def _rand_phone(lang: str) -> str:
    if lang == "fr":
        return f"+33 6 {random.randint(10,99)} {random.randint(10,99)} {random.randint(10,99)} {random.randint(10,99)}"
    if lang == "na":
        return f"+213 5{random.randint(50,59)} {random.randint(100,999)} {random.randint(100,999)}"
    return f"+1 {random.randint(200,999)} {random.randint(100,999)} {random.randint(1000,9999)}"


def _rand_name(lang: str) -> tuple[str, str]:
    if lang == "fr":
        first = random.choice(FR_FIRST_M + FR_FIRST_F)
        last = random.choice(FR_LAST)
    elif lang == "na":
        first = random.choice(NA_FIRST_M + NA_FIRST_F)
        last = random.choice(NA_LAST)
    else:
        first = random.choice(EN_FIRST_M + EN_FIRST_F)
        last = random.choice(EN_LAST)
    return first, last


def _rand_experience(
    dept_cfg: dict, lang: str, total_years: int
) -> list[dict]:
    companies = dept_cfg.get(f"companies_{lang}", dept_cfg.get("companies_en", []))
    titles_key = "titles_fr" if lang in ("fr", "na") else "titles_en"
    titles = dept_cfg.get(titles_key, dept_cfg["titles_en"])

    num_jobs = min(random.randint(1, 5), max(1, total_years // 2))
    current_year = 2025
    entries = []
    remaining = total_years

    for i in range(num_jobs):
        if remaining <= 0:
            break
        duration = max(1, min(remaining, random.randint(1, 5)))
        end_year = current_year
        start_year = current_year - duration
        end_str = "present" if i == 0 else f"{end_year}-{random.randint(1,12):02d}"
        start_str = f"{start_year}-{random.randint(1,12):02d}"

        entries.append({
            "company": random.choice(companies),
            "role": random.choice(titles),
            "start_date": start_str,
            "end_date": end_str,
            "description": None,
            "location": None,
        })
        current_year = start_year
        remaining -= duration

    return entries


def _rand_education(lang: str, dept_cfg: dict) -> list[dict]:
    num = random.randint(1, 3)
    entries = []
    if lang in ("fr", "na"):
        unis = UNIVERSITIES_FR if lang == "fr" else UNIVERSITIES_NA
        fields = dept_cfg.get("edu_fields_fr", dept_cfg.get("edu_fields_en"))
        degrees = DEGREES_FR
    else:
        unis = UNIVERSITIES_EN
        fields = dept_cfg.get("edu_fields_en", [])
        degrees = DEGREES_EN

    for i in range(num):
        entries.append({
            "institution": random.choice(unis),
            "degree": random.choice(degrees),
            "field": random.choice(fields),
            "year": str(random.randint(2000, 2022)),
        })
    return entries


def _rand_languages(lang: str) -> list[dict]:
    if lang == "fr":
        langs = [
            {"language": "Français", "level": "native"},
            {"language": "Anglais", "level": random.choice(["fluent", "advanced", "intermediate"])},
        ]
        if random.random() < 0.3:
            langs.append({"language": "Espagnol", "level": random.choice(["intermediate", "beginner"])})
    elif lang == "na":
        langs = [
            {"language": "Arabe", "level": "native"},
            {"language": "Français", "level": random.choice(["native", "fluent"])},
            {"language": "Anglais", "level": random.choice(["fluent", "advanced", "intermediate"])},
        ]
    else:
        langs = [
            {"language": "English", "level": "native"},
        ]
        if random.random() < 0.4:
            langs.append({"language": "French", "level": random.choice(["intermediate", "beginner"])})
        if random.random() < 0.2:
            langs.append({"language": "Spanish", "level": random.choice(["advanced", "intermediate"])})
    return langs


def _rand_achievements(lang: str, count: int) -> list[dict]:
    verbs = ACHIEVEMENT_VERBS_FR if lang in ("fr", "na") else ACHIEVEMENT_VERBS_EN
    objects = ACHIEVEMENT_OBJECTS_FR if lang in ("fr", "na") else ACHIEVEMENT_OBJECTS_EN
    achievements = []
    for _ in range(count):
        achievements.append({
            "title": f"{random.choice(verbs)} {random.choice(objects)}",
            "year": str(random.randint(2016, 2025)) if random.random() > 0.3 else None,
            "description": None,
        })
    return achievements


def generate_cv(dept_name: str, dept_cfg: dict, index: int) -> dict:
    lang_weights = {"en": 0.5, "fr": 0.35, "na": 0.15}
    lang = random.choices(list(lang_weights.keys()), weights=list(lang_weights.values()))[0]

    first, last = _rand_name(lang)
    name = f"{first} {last}"
    email = f"{first.lower().replace('é','e').replace('è','e').replace('ê','e').replace('ë','e').replace('à','a').replace('ç','c')}.{last.lower().replace(' ','').replace('é','e').replace('è','e')}@{random.choice(EMAIL_DOMAINS)}"
    phone = _rand_phone(lang)

    if lang == "fr":
        location = random.choice(FR_LOCATIONS)
    elif lang == "na":
        location = random.choice(NA_LOCATIONS)
    else:
        location = random.choice(EN_LOCATIONS)

    total_years = random.randint(2, 20)
    skills = random.sample(dept_cfg["skills"], k=min(random.randint(6, 15), len(dept_cfg["skills"])))

    titles_key = "titles_fr" if lang in ("fr", "na") else "titles_en"
    current_title = random.choice(dept_cfg.get(titles_key, dept_cfg["titles_en"]))

    tpl = random.choice(SUMMARIES_FR if lang in ("fr", "na") else SUMMARIES_EN)
    field_label = random.choice(
        dept_cfg.get("edu_fields_fr" if lang in ("fr", "na") else "edu_fields_en",
                     dept_cfg.get("edu_fields_en", ["technology"]))
    )
    summary = tpl.format(
        title=current_title,
        years=total_years,
        field=field_label,
        skill1=skills[0] if skills else "analysis",
        skill2=skills[1] if len(skills) > 1 else "management",
        skill3=skills[2] if len(skills) > 2 else "communication",
    )

    certs = random.sample(dept_cfg["certs"], k=min(random.randint(0, 3), len(dept_cfg["certs"])))
    achievements = _rand_achievements(lang, random.randint(0, 4))

    profile = {
        "name": name,
        "email": email,
        "phone": phone,
        "location": location,
        "current_title": current_title,
        "summary": summary,
        "linkedin_url": f"https://linkedin.com/in/{first.lower().replace('é','e')}-{last.lower().replace(' ','-')}",
        "github_url": f"https://github.com/{first.lower().replace('é','e')}{last.lower().replace(' ','')}" if dept_name in ("software_engineering", "data_science", "devops", "cybersecurity") and random.random() > 0.3 else None,
        "portfolio_url": None,
        "skills": skills,
        "experience": _rand_experience(dept_cfg, lang, total_years),
        "education": _rand_education(lang, dept_cfg),
        "languages": _rand_languages(lang),
        "certifications": certs,
        "achievements": achievements,
        "total_experience_years": float(total_years),
    }

    return {
        "department": dept_name,
        "language": "fr" if lang in ("fr", "na") else "en",
        "profile": profile,
    }


# ────────────────────────────────────────────────────────────
# Job description generation
# ────────────────────────────────────────────────────────────
JD_TEMPLATES_EN = [
    "We are looking for a talented {title} to join our {dept} team. The ideal candidate has {min_exp}+ years of experience and strong skills in {skills}. You will be responsible for driving key initiatives and collaborating with cross-functional teams.",
    "Join our growing {dept} department as a {title}. We need someone with at least {min_exp} years of hands-on experience in {skills}. This role offers the opportunity to work on challenging projects and make a significant impact.",
    "{title} needed for our {dept} division. Requirements: {min_exp}+ years experience, proficiency in {skills}. The successful candidate will lead projects, mentor junior team members, and contribute to strategic planning.",
]
JD_TEMPLATES_FR = [
    "Nous recherchons un(e) {title} talentueux(se) pour rejoindre notre équipe {dept}. Le candidat idéal possède {min_exp}+ années d'expérience et de solides compétences en {skills}. Vous serez responsable de piloter des initiatives clés.",
    "Rejoignez notre département {dept} en pleine croissance en tant que {title}. Nous recherchons un profil avec au moins {min_exp} ans d'expérience pratique en {skills}. Ce poste offre l'opportunité de travailler sur des projets stimulants.",
    "Poste de {title} au sein de notre division {dept}. Exigences : {min_exp}+ ans d'expérience, maîtrise de {skills}. Le candidat retenu dirigera des projets et contribuera à la planification stratégique.",
]

DEPT_LABELS_FR = {
    "software_engineering": "Développement Logiciel",
    "data_science": "Science des Données",
    "cybersecurity": "Cybersécurité",
    "devops": "DevOps et Cloud",
    "finance": "Finance",
    "human_resources": "Ressources Humaines",
    "marketing": "Marketing",
    "sales": "Commercial",
    "project_management": "Gestion de Projet",
    "engineering": "Ingénierie",
}


def generate_jd(dept_name: str, dept_cfg: dict, index: int) -> dict:
    is_fr = random.random() < 0.4
    lang = "fr" if is_fr else "en"

    titles_key = "titles_fr" if is_fr else "titles_en"
    title = random.choice(dept_cfg.get(titles_key, dept_cfg["titles_en"]))

    all_skills = dept_cfg["skills"]
    num_required = random.randint(3, 6)
    num_preferred = random.randint(2, 4)
    required_skills = random.sample(all_skills, k=min(num_required, len(all_skills)))
    remaining = [s for s in all_skills if s not in required_skills]
    preferred_skills = random.sample(remaining, k=min(num_preferred, len(remaining)))

    min_exp = random.choice([2, 3, 5, 7, 10])
    skills_str = ", ".join(required_skills[:4])
    dept_label = DEPT_LABELS_FR.get(dept_name, dept_name) if is_fr else dept_name.replace("_", " ").title()

    tpl = random.choice(JD_TEMPLATES_FR if is_fr else JD_TEMPLATES_EN)
    description = tpl.format(title=title, dept=dept_label, min_exp=min_exp, skills=skills_str)

    education_req = None
    if random.random() > 0.3:
        if is_fr:
            education_req = random.choice([
                "Bac+5 en " + random.choice(dept_cfg.get("edu_fields_fr", ["Informatique"])),
                "Diplôme d'ingénieur ou Master en " + random.choice(dept_cfg.get("edu_fields_fr", ["Informatique"])),
                "Bac+3 minimum en " + random.choice(dept_cfg.get("edu_fields_fr", ["Informatique"])),
            ])
        else:
            education_req = random.choice([
                "Bachelor's degree in " + random.choice(dept_cfg.get("edu_fields_en", ["Computer Science"])),
                "Master's degree in " + random.choice(dept_cfg.get("edu_fields_en", ["Engineering"])),
                "BS/MS in " + random.choice(dept_cfg.get("edu_fields_en", ["Technology"])),
            ])

    req_langs = None
    if is_fr:
        req_langs = ["Français"]
        if random.random() > 0.4:
            req_langs.append("Anglais")
    else:
        req_langs = ["English"]
        if random.random() > 0.6:
            req_langs.append("French")

    return {
        "department": dept_name,
        "language": lang,
        "title": title,
        "job_description": description,
        "required_skills": required_skills,
        "preferred_skills": preferred_skills,
        "min_experience_years": min_exp,
        "required_languages": req_langs,
        "education_requirements": education_req,
    }


# ────────────────────────────────────────────────────────────
# PDF generation
# ────────────────────────────────────────────────────────────
def _profile_to_text(profile: dict, lang: str) -> str:
    lines: list[str] = []
    lines.append(profile["name"])
    if profile.get("current_title"):
        lines.append(profile["current_title"])
    lines.append("")

    contact_parts = []
    if profile.get("email"):
        contact_parts.append(profile["email"])
    if profile.get("phone"):
        contact_parts.append(profile["phone"])
    if profile.get("location"):
        contact_parts.append(profile["location"])
    lines.append(" | ".join(contact_parts))
    if profile.get("linkedin_url"):
        lines.append(str(profile["linkedin_url"]))
    if profile.get("github_url"):
        lines.append(str(profile["github_url"]))
    lines.append("")

    header_summary = "RÉSUMÉ" if lang == "fr" else "SUMMARY"
    lines.append(header_summary)
    lines.append(profile.get("summary", ""))
    lines.append("")

    header_exp = "EXPÉRIENCE PROFESSIONNELLE" if lang == "fr" else "WORK EXPERIENCE"
    lines.append(header_exp)
    for exp in profile.get("experience", []):
        period = f"{exp.get('start_date', '')} – {exp.get('end_date', '')}"
        lines.append(f"{exp['company']}")
        lines.append(f"{exp['role']} ({period})")
        if exp.get("description"):
            lines.append(exp["description"])
        lines.append("")

    header_edu = "FORMATION" if lang == "fr" else "EDUCATION"
    lines.append(header_edu)
    for edu in profile.get("education", []):
        line = f"{edu['institution']}"
        if edu.get("degree"):
            line += f" — {edu['degree']}"
        if edu.get("field"):
            line += f" en {edu['field']}" if lang == "fr" else f" in {edu['field']}"
        if edu.get("year"):
            line += f" ({edu['year']})"
        lines.append(line)
    lines.append("")

    header_skills = "COMPÉTENCES" if lang == "fr" else "SKILLS"
    lines.append(header_skills)
    lines.append(", ".join(profile.get("skills", [])))
    lines.append("")

    header_lang = "LANGUES" if lang == "fr" else "LANGUAGES"
    lines.append(header_lang)
    for l_entry in profile.get("languages", []):
        lines.append(f"{l_entry['language']}: {l_entry['level']}")
    lines.append("")

    if profile.get("certifications"):
        header_cert = "CERTIFICATIONS" if lang == "fr" else "CERTIFICATIONS"
        lines.append(header_cert)
        for c in profile["certifications"]:
            lines.append(f"- {c}")
        lines.append("")

    if profile.get("achievements"):
        header_ach = "RÉALISATIONS" if lang == "fr" else "ACHIEVEMENTS"
        lines.append(header_ach)
        for a in profile["achievements"]:
            line = a["title"]
            if a.get("year"):
                line += f" ({a['year']})"
            lines.append(f"- {line}")
        lines.append("")

    return "\n".join(lines)


def generate_pdf(cv_data: dict, output_path: Path) -> None:
    profile = cv_data["profile"]
    lang = cv_data["language"]
    text = _profile_to_text(profile, lang)

    pdf = FPDF()
    pdf.add_font("DejaVu", "", FONT_PATH)
    pdf.add_font("DejaVu", "B", FONT_BOLD_PATH)
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=20)

    NX, NY = "LMARGIN", "NEXT"

    text = _profile_to_text(profile, lang)
    for line in text.split("\n"):
        stripped = line.strip()
        if stripped.isupper() and len(stripped) > 3:
            pdf.set_font("DejaVu", "B", 12)
            pdf.multi_cell(0, 7, stripped, new_x=NX, new_y=NY)
            pdf.ln(1)
        elif stripped:
            pdf.set_font("DejaVu", "", 10)
            pdf.multi_cell(0, 5, stripped, new_x=NX, new_y=NY)
        else:
            pdf.ln(3)

    pdf.output(str(output_path))


def _render_text_to_images(text: str, *, dpi: int = 150) -> list:
    """Rasterize CV text into one or more page images (PIL).

    Letter-sized pages at the given DPI. Lines that are ALL CAPS and longer
    than 3 chars render as bold section headers (matching `generate_pdf`).
    """
    from PIL import Image, ImageDraw, ImageFont

    width, height = int(8.5 * dpi), int(11 * dpi)
    margin = int(0.6 * dpi)
    font_regular = ImageFont.truetype(FONT_PATH, max(12, int(0.11 * dpi)))
    font_bold = ImageFont.truetype(FONT_BOLD_PATH, max(15, int(0.14 * dpi)))
    line_h_reg = max(16, int(0.16 * dpi))
    line_h_bold = max(22, int(0.21 * dpi))
    blank_gap = max(6, int(0.06 * dpi))

    pages: list = []
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    y = margin

    def _flush_page() -> None:
        nonlocal img, draw, y
        pages.append(img)
        img = Image.new("RGB", (width, height), "white")
        draw = ImageDraw.Draw(img)
        y = margin

    for line in text.split("\n"):
        stripped = line.strip()
        if not stripped:
            y += blank_gap
            if y > height - margin:
                _flush_page()
            continue
        is_header = stripped.isupper() and len(stripped) > 3
        font = font_bold if is_header else font_regular
        lh = line_h_bold if is_header else line_h_reg
        if y + lh > height - margin:
            _flush_page()
        draw.text((margin, y), stripped, fill="black", font=font)
        y += lh

    pages.append(img)
    return pages


def generate_image_pdf(cv_data: dict, output_path: Path, *, dpi: int = 150) -> None:
    """Generate an image-only PDF (no text layer) to exercise the OCR pipeline.

    The output PDF embeds the CV as rasterized page images, so PyMuPDF native
    text extraction returns ~empty and the EasyOCR path
    (`app/services/ocr_service.py`) fires when the file is uploaded.
    """
    text = _profile_to_text(cv_data["profile"], cv_data["language"])
    pages = _render_text_to_images(text, dpi=dpi)
    pages[0].save(
        str(output_path),
        "PDF",
        save_all=True,
        append_images=pages[1:],
        resolution=float(dpi),
    )


# ────────────────────────────────────────────────────────────
# Main
# ────────────────────────────────────────────────────────────
def main() -> None:
    parser = argparse.ArgumentParser(description="Generate E2E test data")
    parser.add_argument("--cvs", type=int, default=210, help="Number of CVs to generate")
    parser.add_argument("--jds", type=int, default=55, help="Number of JDs to generate")
    parser.add_argument("--pdfs", type=int, default=50, help="Number of text-layer PDFs to generate")
    parser.add_argument(
        "--image-pdfs",
        type=int,
        default=0,
        help="Number of image-only PDFs (no text layer) to generate for OCR-path testing",
    )
    parser.add_argument(
        "--image-dpi", type=int, default=150, help="DPI for image-only PDFs (default 150)"
    )
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    args = parser.parse_args()

    random.seed(args.seed)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "pdfs").mkdir(exist_ok=True)

    dept_names = list(DEPARTMENTS.keys())
    cvs_per_dept = args.cvs // len(dept_names)
    extra_cvs = args.cvs % len(dept_names)

    print(f"Generating {args.cvs} CVs across {len(dept_names)} departments...")
    all_cvs = []
    for i, dept_name in enumerate(dept_names):
        count = cvs_per_dept + (1 if i < extra_cvs else 0)
        for j in range(count):
            cv = generate_cv(dept_name, DEPARTMENTS[dept_name], j)
            all_cvs.append(cv)

    random.shuffle(all_cvs)

    cvs_path = OUTPUT_DIR / "cvs.json"
    with open(cvs_path, "w", encoding="utf-8") as f:
        json.dump(all_cvs, f, ensure_ascii=False, indent=2)
    print(f"  → {cvs_path} ({len(all_cvs)} CVs)")

    jds_per_dept = args.jds // len(dept_names)
    extra_jds = args.jds % len(dept_names)

    print(f"Generating {args.jds} job descriptions...")
    all_jds = []
    for i, dept_name in enumerate(dept_names):
        count = jds_per_dept + (1 if i < extra_jds else 0)
        for j in range(count):
            jd = generate_jd(dept_name, DEPARTMENTS[dept_name], j)
            all_jds.append(jd)

    random.shuffle(all_jds)

    jds_path = OUTPUT_DIR / "jds.json"
    with open(jds_path, "w", encoding="utf-8") as f:
        json.dump(all_jds, f, ensure_ascii=False, indent=2)
    print(f"  → {jds_path} ({len(all_jds)} JDs)")

    pdf_count = min(args.pdfs, len(all_cvs))
    print(f"Generating {pdf_count} PDF files...")
    for i in range(pdf_count):
        cv = all_cvs[i]
        safe_name = cv["profile"]["name"].replace(" ", "_").replace("'", "")
        filename = f"cv_{i+1:03d}_{safe_name}.pdf"
        pdf_path = OUTPUT_DIR / "pdfs" / filename
        try:
            generate_pdf(cv, pdf_path)
        except Exception as e:
            print(f"  ⚠ Failed to generate PDF for {cv['profile']['name']}: {e}")
            continue

    pdf_files = list((OUTPUT_DIR / "pdfs").glob("*.pdf"))
    print(f"  → {OUTPUT_DIR / 'pdfs'} ({len(pdf_files)} PDFs)")

    if args.image_pdfs > 0:
        img_pdf_dir = OUTPUT_DIR / "pdfs"
        img_count = min(args.image_pdfs, len(all_cvs))
        # Offset past the text PDFs so image and text PDFs cover different CVs
        # and end up in the same data/pdfs/ directory.
        offset = pdf_count
        if offset + img_count > len(all_cvs):
            img_count = max(0, len(all_cvs) - offset)
        print(f"Generating {img_count} image-only PDFs at {args.image_dpi} DPI (OCR path)...")
        for i in range(img_count):
            cv = all_cvs[offset + i]
            safe_name = cv["profile"]["name"].replace(" ", "_").replace("'", "")
            filename = f"cv_{offset + i + 1:03d}_{safe_name}_ocr.pdf"
            out_path = img_pdf_dir / filename
            try:
                generate_image_pdf(cv, out_path, dpi=args.image_dpi)
            except Exception as e:
                print(f"  ⚠ Failed to generate image PDF for {cv['profile']['name']}: {e}")
                continue
        img_files = list(img_pdf_dir.glob("*_ocr.pdf"))
        print(f"  → {img_pdf_dir} ({len(img_files)} image PDFs added)")

    stats = {}
    for cv in all_cvs:
        dept = cv["department"]
        lang = cv["language"]
        stats.setdefault(dept, {"en": 0, "fr": 0})
        stats[dept][lang] = stats[dept].get(lang, 0) + 1

    print("\nDistribution:")
    print(f"  {'Department':<25} {'EN':>5} {'FR':>5} {'Total':>6}")
    print(f"  {'─' * 25} {'─' * 5} {'─' * 5} {'─' * 6}")
    for dept, counts in sorted(stats.items()):
        total = sum(counts.values())
        print(f"  {dept:<25} {counts.get('en', 0):>5} {counts.get('fr', 0):>5} {total:>6}")
    grand_en = sum(c.get("en", 0) for c in stats.values())
    grand_fr = sum(c.get("fr", 0) for c in stats.values())
    print(f"  {'TOTAL':<25} {grand_en:>5} {grand_fr:>5} {grand_en + grand_fr:>6}")

    print("\nDone.")


if __name__ == "__main__":
    main()
