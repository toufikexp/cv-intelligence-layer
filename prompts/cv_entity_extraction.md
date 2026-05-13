# CV Entity Extraction Prompt

## System Prompt

You are a precise CV/resume parser. Extract structured candidate information from the provided CV text. The CV may be in French or English. Return ONLY valid JSON — no markdown, no explanation, no preamble.

## User Prompt Template

```
Extract structured candidate information from the following CV text.

**CV Language**: {detected_language}
**Extraction Notes**: {extraction_notes}

---

{cv_text}

---

Rules:
1. If a field cannot be determined from the CV, set it to null (for scalars) or empty array (for arrays).
2. Normalize skill names: capitalize properly (e.g., "python" → "Python", "machine learning" → "Machine Learning").
3. For French CVs: translate degree names to their French equivalents (Licence, Master, Ingénieur, BTS, DUT). Keep company names and proper nouns in their original language.
4. For experience entries: order from most recent to oldest.
5. For phone numbers: normalize to international format (e.g., +213 XXX XXX XXX for Algerian, +33 X XX XX XX XX for French).
6. Estimate total_experience_years by summing non-overlapping employment periods. If dates are ambiguous, provide a best estimate.
7. Achievements are **discrete, named projects/realizations** that stand on their own — typically found under headings like "Projets", "Réalisations", "Key Projects", "Achievements", "Projets notables". Do NOT duplicate generic job responsibilities already captured in `experience[].description`. If the CV has no such section and no clearly-named project, return an empty array.
8. Return ONLY the JSON object. No markdown backticks, no explanation text.
```

## Few-Shot Examples

### Example 1: French CV

**Input (excerpt)**:
```
AHMED BENALI
Ingénieur Data Senior
Alger, Algérie
ahmed.benali@email.com | +213 555 123 456

EXPÉRIENCE PROFESSIONNELLE

Ooredoo Algérie — Data Engineer Senior (Janvier 2022 – Présent)
- Conception de pipelines ETL avec Python et Apache Spark
- Mise en place d'un datamart client 360 avec PostgreSQL

Djezzy — Analyste BI (Mars 2019 – Décembre 2021)
- Création de tableaux de bord Power BI pour le suivi commercial
- Analyse de la performance réseau

RÉALISATIONS & PROJETS
- Migration Data Lake vers AWS (2023) — Pilotage de la migration complète de l'infrastructure data vers AWS S3 + Glue + Athena. Réduction des coûts opérationnels de 35% et amélioration des temps de traitement de 60%.
- Implémentation du modèle ML Churn Prediction (2022) — Développement et déploiement d'un modèle de prédiction du churn client avec une précision de 87%.

FORMATION
Master en Informatique — Université USTHB, Alger (2018)
Licence en Mathématiques et Informatique — Université USTHB (2016)

COMPÉTENCES
Python, SQL, Apache Spark, Power BI, PostgreSQL, ETL, Machine Learning

LANGUES
Arabe (natif), Français (courant), Anglais (intermédiaire)
```

**Expected Output**:
```json
{
  "name": "Ahmed Benali",
  "email": "ahmed.benali@email.com",
  "phone": "+213 555 123 456",
  "location": "Alger, Algérie",
  "current_title": "Ingénieur Data Senior",
  "summary": "Senior Data Engineer with experience in ETL pipelines, customer 360 datamarts, and BI reporting in the telecom sector.",
  "linkedin_url": null,
  "github_url": null,
  "portfolio_url": null,
  "skills": ["Python", "SQL", "Apache Spark", "Power BI", "PostgreSQL", "ETL", "Machine Learning"],
  "experience": [
    {
      "company": "Ooredoo Algérie",
      "role": "Data Engineer Senior",
      "start_date": "2022-01",
      "end_date": "present",
      "description": "Designed ETL pipelines with Python and Apache Spark. Built a customer 360 datamart with PostgreSQL.",
      "location": null
    },
    {
      "company": "Djezzy",
      "role": "Analyste BI",
      "start_date": "2019-03",
      "end_date": "2021-12",
      "description": "Created Power BI dashboards for sales tracking. Analyzed network performance.",
      "location": null
    }
  ],
  "education": [
    {
      "institution": "Université USTHB",
      "degree": "Master",
      "field": "Informatique",
      "year": "2018"
    },
    {
      "institution": "Université USTHB",
      "degree": "Licence",
      "field": "Mathématiques et Informatique",
      "year": "2016"
    }
  ],
  "languages": [
    { "language": "Arabic", "level": "native" },
    { "language": "French", "level": "fluent" },
    { "language": "English", "level": "intermediate" }
  ],
  "certifications": [],
  "achievements": [
    {
      "title": "Migration Data Lake vers AWS",
      "year": "2023",
      "description": "Pilotage de la migration complète de l'infrastructure data vers AWS S3 + Glue + Athena. Réduction des coûts opérationnels de 35% et amélioration des temps de traitement de 60%."
    },
    {
      "title": "Implémentation du modèle ML Churn Prediction",
      "year": "2022",
      "description": "Développement et déploiement d'un modèle de prédiction du churn client avec une précision de 87%."
    }
  ],
  "total_experience_years": 6
}
```

### Example 2: English CV

**Input (excerpt)**:
```
Sarah Johnson
Full Stack Developer
London, UK | sarah.j@proton.me | +44 7911 123456
linkedin.com/in/sarahjohnson | github.com/sarahj

PROFESSIONAL EXPERIENCE

TechCorp Ltd — Senior Developer (June 2021 – Present)
Led a team of 4 developers building microservices with Node.js and React.
Reduced API response time by 40% through caching optimization.

StartupXYZ — Junior Developer (Sep 2019 – May 2021)
Built customer-facing features using React and TypeScript.
Implemented CI/CD pipelines with GitHub Actions.

EDUCATION
BSc Computer Science — University of Manchester (2019)

SKILLS
JavaScript, TypeScript, React, Node.js, PostgreSQL, Docker, AWS, CI/CD

CERTIFICATIONS
AWS Solutions Architect Associate (2023)
```

**Expected Output**:
```json
{
  "name": "Sarah Johnson",
  "email": "sarah.j@proton.me",
  "phone": "+44 7911 123456",
  "location": "London, UK",
  "current_title": "Senior Developer",
  "summary": "Full Stack Developer with 5+ years of experience in React, Node.js, and microservices architecture.",
  "linkedin_url": "https://linkedin.com/in/sarahjohnson",
  "github_url": "https://github.com/sarahj",
  "portfolio_url": null,
  "skills": ["JavaScript", "TypeScript", "React", "Node.js", "PostgreSQL", "Docker", "AWS", "CI/CD"],
  "experience": [
    {
      "company": "TechCorp Ltd",
      "role": "Senior Developer",
      "start_date": "2021-06",
      "end_date": "present",
      "description": "Led a team of 4 developers building microservices with Node.js and React. Reduced API response time by 40% through caching optimization.",
      "location": null
    },
    {
      "company": "StartupXYZ",
      "role": "Junior Developer",
      "start_date": "2019-09",
      "end_date": "2021-05",
      "description": "Built customer-facing features using React and TypeScript. Implemented CI/CD pipelines with GitHub Actions.",
      "location": null
    }
  ],
  "education": [
    {
      "institution": "University of Manchester",
      "degree": "Bachelor",
      "field": "Computer Science",
      "year": "2019"
    }
  ],
  "languages": [],
  "certifications": ["AWS Solutions Architect Associate (2023)"],
  "achievements": [],
  "total_experience_years": 5
}
```

## Usage Notes

- The `{detected_language}` placeholder should be filled with the output of fasttext language detection (e.g., "fr", "en", "mixed").
- The `{extraction_notes}` placeholder can include: "Text extracted via OCR — may contain artifacts" or "Clean text extraction from PDF" to help the LLM handle noisy input.
- Always validate the LLM output against the `CandidateProfile` Pydantic schema. Use `model_validate()` with `strict=False` to handle minor deviations.
- If the LLM returns invalid JSON, retry once with a shorter prompt that omits examples.
