# CV Entity Extraction Prompt

## System Prompt

You are a precise CV/resume parser. Extract structured candidate information from the provided CV text. The CV may be in French or English. Return ONLY valid JSON matching the schema below — no markdown, no explanation, no preamble.

## User Prompt Template

```
Extract structured candidate information from a CV. The CV text appears at the
very end, after the schema and rules below.

Return a JSON object matching this exact schema:

{
  "summary": "Professional summary or objective, 1-3 sentences (string or null)",
  "function": "Most recent job title / function (string or null)",
  "skills": [
    {
      "name": "Skill name — MUST be copied EXACTLY from the controlled vocabulary list below. Skills not in that list are NOT allowed.",
      "score": "Proficiency level: BASIC | INTERMEDIATE | ADVANCED | EXPERT | MASTER"
    }
  ],
  "experiences": [
    {
      "role": "Job title (string)",
      "company": "Company name (string)",
      "startDate": "YYYY-MM-DD or YYYY-MM or YYYY (string)",
      "endDate": "YYYY-MM-DD, YYYY-MM, YYYY, or 'present' (string)",
      "description": "Key responsibilities and achievements, 1-3 sentences (string or null)"
    }
  ],
  "educations": [
    {
      "establishment": "University or school name (string — pick from the predefined list below when a clear match exists; otherwise use the exact name from the CV)",
      "fieldOfStudy": "Field of study (string or null)",
      "typeEducation": "LICENCE | MASTER | DOCTORAT | BACHELOR | MBA | INGENIEUR | BTS | DUT | FORMATION_PROFESSIONNELLE",
      "dateGraduation": "Graduation year YYYY (string or null)"
    }
  ],
  "languages": [
    {
      "language": "Language name — pick from the predefined languages list below and copy the name EXACTLY as written. If the CV's language is not in the list, use the language name in English.",
      "proficiency": "A1 | A2 | B1 | B2 | C1 | C2 | NATIVE"
    }
  ],
  "certifications": [
    {
      "title": "Certification name (string)",
      "issuer": "Issuing body (string or null)",
      "issueDate": "YYYY-MM-DD or YYYY (string or null)",
      "expiryDate": "YYYY-MM-DD or YYYY (string or null)",
      "description": "Brief description (string or null)"
    }
  ],
  "achievements": [
    {
      "title": "Short name of the project or realization (string, required)",
      "description": "1-2 sentence description highlighting scope and measurable impact (string or null)",
      "startDate": "YYYY-MM-DD or YYYY (string or null)",
      "endDate": "YYYY-MM-DD or YYYY (string or null)"
    }
  ]
}

Rules:
1. If a field cannot be determined from the CV, set it to null (for scalars) or empty array (for arrays).
2. Normalize skill names: capitalize properly (e.g., "python" → "Python", "machine learning" → "Machine Learning").
3. For French CVs: translate degree names to their French equivalents (Licence, Master, Ingénieur, BTS, DUT). Keep company names and proper nouns in their original language.
4. For experience entries: order from most recent to oldest.
5. Estimate function from the most recent role/title.
6. Achievements are **discrete, named projects/realizations** that stand on their own — typically found under headings like "Projets", "Réalisations", "Key Projects", "Achievements", "Projets notables". Do NOT duplicate generic job responsibilities already captured in `experiences[].description`. If the CV has no such section and no clearly-named project, return an empty array.
7. Return ONLY the JSON object. No markdown backticks, no explanation text.
8. Personal information (name, email, phone, location, URLs, date of birth) has been redacted for privacy. Placeholders like [REDACTED_NAME], [REDACTED_EMAIL], [REDACTED_PHONE], [REDACTED_LOCATION], [REDACTED_URL], [REDACTED_DOB] may appear in the text. Do NOT try to extract personal information — focus on function, summary, skills, experiences, educations, languages, certifications, and achievements.
9. Skills vocabulary (STRICT — closed list): a controlled list of canonical skill names is provided below. Return ONLY skills whose name appears in that list, copied **exactly** as written (same spelling, casing, punctuation). If a skill in the CV is **not** in the list, **OMIT it entirely** — do not output it, do not invent a near-match, do not keep the CV's own wording. It is correct and expected for the `skills` array to be short or empty when the CV's skills are not in the vocabulary. Never output a skill that is not in the list.
10. Skill score: for each skill, assess proficiency from the CV context using ONLY these values: BASIC, INTERMEDIATE, ADVANCED, EXPERT, MASTER. Base your assessment on evidence in the CV (years of use, project depth, certifications). If uncertain, use INTERMEDIATE.
11. Languages: a predefined list of language names is provided below. For each language in the CV, output the name copied **exactly** from that list when it matches; if the CV's language is not in the list, output its English name. Assess proficiency using ONLY these CEFR values: A1, A2, B1, B2, C1, C2, NATIVE. Map common descriptions: "natif/maternelle" → NATIVE, "courant/fluent" → C1, "avancé/advanced" → B2, "intermédiaire/intermediate" → B1, "débutant/beginner/basic" → A1.
12. Education type: use ONLY these values: LICENCE, MASTER, DOCTORAT, BACHELOR, MBA, INGENIEUR, BTS, DUT, FORMATION_PROFESSIONNELLE. Map common terms: "BSc/BA" → BACHELOR, "MSc/MA" → MASTER, "PhD" → DOCTORAT, "Diplôme d'ingénieur" → INGENIEUR.
13. Establishment: pick from the predefined establishments list below when the CV's institution clearly matches one. If no match, use the institution name exactly as written in the CV.

Controlled skill vocabulary (canonical names; use exact spelling when a match is clear):
{skills_catalog}

Predefined establishments (use exact name when the CV's institution matches):
{establishments_list}

Predefined languages (copy the name exactly when the CV's language matches):
{languages_list}

<<<CV_INPUT>>>
**CV Language**: {detected_language}
**Extraction Notes**: {extraction_notes}

--- CV TEXT START ---
{cv_text}
--- CV TEXT END ---
```

## Few-Shot Examples

> Note: the `skills` arrays in the examples below assume every skill shown is present in the controlled vocabulary. At runtime, apply rule 9 strictly — output a skill ONLY if it appears in the vocabulary list, otherwise omit it.

### Example 1: French CV

**Input (excerpt)**:
```
[REDACTED_NAME]
Ingénieur Data Senior
[REDACTED_LOCATION]
[REDACTED_EMAIL] | [REDACTED_PHONE]

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
  "summary": "Senior Data Engineer with experience in ETL pipelines, customer 360 datamarts, and BI reporting in the telecom sector.",
  "function": "Data Engineer Senior",
  "skills": [
    { "name": "Python", "score": "ADVANCED" },
    { "name": "SQL", "score": "ADVANCED" },
    { "name": "Apache Spark", "score": "INTERMEDIATE" },
    { "name": "Power BI", "score": "INTERMEDIATE" },
    { "name": "PostgreSQL", "score": "ADVANCED" },
    { "name": "ETL", "score": "ADVANCED" },
    { "name": "Machine Learning", "score": "INTERMEDIATE" }
  ],
  "experiences": [
    {
      "role": "Data Engineer Senior",
      "company": "Ooredoo Algérie",
      "startDate": "2022-01",
      "endDate": "present",
      "description": "Designed ETL pipelines with Python and Apache Spark. Built a customer 360 datamart with PostgreSQL."
    },
    {
      "role": "Analyste BI",
      "company": "Djezzy",
      "startDate": "2019-03",
      "endDate": "2021-12",
      "description": "Created Power BI dashboards for sales tracking. Analyzed network performance."
    }
  ],
  "educations": [
    {
      "establishment": "Université des Sciences et de la Technologie Houari Boumediene (USTHB)",
      "fieldOfStudy": "Informatique",
      "typeEducation": "MASTER",
      "dateGraduation": "2018"
    },
    {
      "establishment": "Université des Sciences et de la Technologie Houari Boumediene (USTHB)",
      "fieldOfStudy": "Mathématiques et Informatique",
      "typeEducation": "LICENCE",
      "dateGraduation": "2016"
    }
  ],
  "languages": [
    { "language": "Arabic", "proficiency": "NATIVE" },
    { "language": "French", "proficiency": "C1" },
    { "language": "English", "proficiency": "B1" }
  ],
  "certifications": [],
  "achievements": [
    {
      "title": "Migration Data Lake vers AWS",
      "description": "Pilotage de la migration complète de l'infrastructure data vers AWS S3 + Glue + Athena. Réduction des coûts opérationnels de 35% et amélioration des temps de traitement de 60%.",
      "startDate": "2023",
      "endDate": null
    },
    {
      "title": "Implémentation du modèle ML Churn Prediction",
      "description": "Développement et déploiement d'un modèle de prédiction du churn client avec une précision de 87%.",
      "startDate": "2022",
      "endDate": null
    }
  ]
}
```

### Example 2: English CV

**Input (excerpt)**:
```
[REDACTED_NAME]
Full Stack Developer
[REDACTED_LOCATION] | [REDACTED_EMAIL] | [REDACTED_PHONE]
[REDACTED_URL] | [REDACTED_URL]

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
  "summary": "Full Stack Developer with 5+ years of experience in React, Node.js, and microservices architecture.",
  "function": "Senior Developer",
  "skills": [
    { "name": "JavaScript", "score": "ADVANCED" },
    { "name": "TypeScript", "score": "ADVANCED" },
    { "name": "React", "score": "ADVANCED" },
    { "name": "Node.js", "score": "ADVANCED" },
    { "name": "PostgreSQL", "score": "INTERMEDIATE" },
    { "name": "Docker", "score": "INTERMEDIATE" },
    { "name": "AWS", "score": "INTERMEDIATE" },
    { "name": "CI/CD", "score": "INTERMEDIATE" }
  ],
  "experiences": [
    {
      "role": "Senior Developer",
      "company": "TechCorp Ltd",
      "startDate": "2021-06",
      "endDate": "present",
      "description": "Led a team of 4 developers building microservices with Node.js and React. Reduced API response time by 40% through caching optimization."
    },
    {
      "role": "Junior Developer",
      "company": "StartupXYZ",
      "startDate": "2019-09",
      "endDate": "2021-05",
      "description": "Built customer-facing features using React and TypeScript. Implemented CI/CD pipelines with GitHub Actions."
    }
  ],
  "educations": [
    {
      "establishment": "University of Manchester",
      "fieldOfStudy": "Computer Science",
      "typeEducation": "BACHELOR",
      "dateGraduation": "2019"
    }
  ],
  "languages": [],
  "certifications": [
    {
      "title": "AWS Solutions Architect Associate",
      "issuer": "Amazon Web Services",
      "issueDate": "2023",
      "expiryDate": null,
      "description": null
    }
  ],
  "achievements": []
}
```

## Usage Notes

- The `{detected_language}` placeholder should be filled with the output of fasttext language detection (e.g., "fr", "en", "mixed").
- The `{extraction_notes}` placeholder can include: "Text extracted via OCR — may contain artifacts" or "Clean text extraction from document" to help the LLM handle noisy input.
- Always validate the LLM output against the `CandidateProfile` Pydantic schema. Use `model_validate()` with `strict=False` to handle minor deviations.
- If the LLM returns invalid JSON, retry once with a shorter prompt that omits examples.
