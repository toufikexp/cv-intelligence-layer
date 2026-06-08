"""Seed SkillConnect catalogs: skills, establishments, languages.

Populates the catalog tables created in 0004 with the authoritative reference
data from ``skillConnect_details_v_1.0.docx``:

- 221 skills (code, name, category, external_id)
- 67 establishments (code, name)
- 5 languages (code, name)

Idempotent: every row is an upsert (INSERT ... ON CONFLICT (code) DO UPDATE),
so re-running is safe and the live SkillConnect API refresh keeps upserting on
top of this baseline. Establishment codes ``USA`` and ``UTI`` each appear twice
in the source for two distinct universities; the second occurrence is suffixed
``_2`` to keep the primary key unique without dropping data (establishment codes
are internal-only — resolution is by name).

Uses SQLAlchemy Core + the PostgreSQL ON CONFLICT construct so it compiles to
the correct paramstyle under the project's asyncpg driver.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import insert as pg_insert

revision = "0006_seed_skillconnect_catalogs"
down_revision = "0005_drop_skillconnect_profile"
branch_labels = None
depends_on = None


# (code, name, category, external_id)
SKILLS: list[tuple[str, str, str | None, int | None]] = [
    ('NET_ACC_DESIGN', 'Access Network Design & Planning', 'Network', 1),
    ('NET_ACC_OPS', 'Access Network Operations', 'Network', 2),
    ('FIN_ACC_SYS', 'Accounting Information Systems', 'Finance', 3),
    ('FIN_ACC_STD', 'Accounting Standards', 'Finance', 4),
    ('NET_ACTIVE_INFRA', 'Active Infrastructure Rollout', 'Network', 5),
    ('PM_AGILE_SCRUM', 'Agile - Scrum Project Management', 'Project Management', 6),
    ('SOFT_ANALYTIC', 'Analytical Thinking', 'Soft Skills', 7),
    ('DIG_APP_CONTENT', 'Application & Content Development', 'Digital', 8),
    ('CX_B2B_DIGICARE', 'B2B Customer Care - Digital Care', 'Customer Experience', 9),
    ('STRAT_B2B_PORTF', 'B2B Product - Portfolio Strategy Development', 'Business Strategy', 10),
    ('COM_B2B_PRICING', 'B2B Product Pricing & Offering', 'Commercial', 11),
    ('SALES_B2B_SOL', 'B2B Solution Selling', 'Sales', 12),
    ('SALES_B2C', 'B2C Sales', 'Sales', 13),
    ('FIN_BANK_COMPLY', 'Banking & Financial Compliance Regulations', 'Finance', 14),
    ('PROC_TENDER', 'Bidding & Tendering Process', 'Procurement', 15),
    ('DATA_BIGDATA', 'Big Data Management', 'Data', 16),
    ('MKT_BRAND_MGMT', 'Brand Management', 'Marketing', 17),
    ('MKT_BRAND', 'Brand Marketer', 'Marketing', 18),
    ('STRAT_BIZ_CASE', 'Business Case Development', 'Business Strategy', 19),
    ('COMM_BIZ_ENG', 'Business English', 'Communication', 20),
    ('STRAT_BIZ_MODEL', 'Business Modeling', 'Business Strategy', 21),
    ('OPS_BPM', 'Business Process Management (BPM)', 'Operations', 22),
    ('STRAT_BUSINESS', 'Business Strategist', 'Business Strategy', 23),
    ('MKT_CAMPAIGN', 'Campaign Management', 'Marketing', 24),
    ('CX_VOC', 'Capturing the Voice of the Customer (VoC)', 'Customer Experience', 25),
    ('FIN_CASH', 'Cash Management', 'Finance', 26),
    ('COM_CATEGORY', 'Category Development & Management', 'Commercial', 27),
    ('COM_CATEGORY_KNOW', 'Category Specific Knowledge', 'Commercial', 28),
    ('IT_CHANGE_REL', 'Change & Release Management', 'IT Operations', 29),
    ('CLOUD_SERVICES', 'Cloud Based Services', 'Cloud', 30),
    ('CX_COMPLAINT', 'Complaint Management & Resolution', 'Customer Experience', 31),
    ('IT_OFFICE_TECH', 'Computer & Office Technology', 'IT', 32),
    ('PM_GTM', 'Concept to Market - Go to Market', 'Product Management', 33),
    ('ANALYTICS_CONSUMER', 'Consumer Analytics', 'Analytics', 34),
    ('CX_CONTACT_CENTER', 'Contact Center Tools', 'Customer Experience', 35),
    ('CONTENT_DESIGN', 'Content Design & Production', 'Content', 36),
    ('OPS_CI', 'Continuous Improvement (CI)', 'Operations', 37),
    ('LEGAL_CONTRACT', 'Contract Support', 'Legal', 38),
    ('TELCO_CONVERGED', 'Converged Products & Services', 'Telecom', 39),
    ('NET_CORE_DESIGN', 'Core Network Design & Planning', 'Network', 40),
    ('CORP_AFFAIRS', 'Corporate Affairs', 'Corporate', 41),
    ('CORP_CSR', 'Corporate Social Responsibility', 'Corporate', 42),
    ('FIN_COST_ACC', 'Cost Accounting & Management', 'Finance', 43),
    ('CONTENT_COPY', 'Creative Copywriting', 'Content', 44),
    ('SOFT_CREATIVE', 'Creative Thinking', 'Soft Skills', 45),
    ('FIN_CREDIT_COLL', 'Credit & Collection Process', 'Finance', 46),
    ('SOFT_CRITICAL', 'Critical Thinking', 'Soft Skills', 47),
    ('SALES_CROSS', 'Cross-Selling', 'Sales', 48),
    ('CX_COMM', 'Customer Communication', 'Customer Experience', 49),
    ('CX_ANALYTICS', 'Customer Experience Analytics', 'Customer Experience', 50),
    ('CX_PRACTICES', 'Customer Experience Practices', 'Customer Experience', 51),
    ('CX_JOURNEY', 'Customer Journey Mapping', 'Customer Experience', 52),
    ('CX_VALUE', 'Customer Value Management', 'Customer Experience', 53),
    ('LOG_CUSTOMS', 'Customs Clearance Process', 'Logistics', 54),
    ('SEC_CYBER', 'Cyber Security', 'Security', 55),
    ('INFRA_DC_DESIGN', 'Data Center Design & Planning', 'Infrastructure', 56),
    ('INFRA_DC_OPS', 'Data Center Operation & Maintenance', 'Infrastructure', 57),
    ('DATA_PIPELINE', 'Data Modeling & Pipelining', 'Data', 58),
    ('DATA_MONETIZE', 'Data Monetization', 'Data', 59),
    ('DESIGN_MGMT', 'Design Management', 'Design', 60),
    ('IT_DEVICE', 'Device Management', 'IT', 61),
    ('DIG_ANALYTICS', 'Digital Analytics', 'Digital', 62),
    ('DIG_BIZ_DEV', 'Digital Business Development', 'Digital', 63),
    ('CX_DIGITAL_CARE', 'Digital Care', 'Customer Experience', 64),
    ('DIG_CHANNEL_COMM', 'Digital Channels Management (Commercial Aspects)', 'Digital', 65),
    ('DIG_CHANNEL_TECH', 'Digital Channels Management (Technical Aspects)', 'Digital', 66),
    ('CONTENT_DIGITAL', 'Digital Content Management', 'Content', 67),
    ('CX_DIGITAL_TECH', 'Digital CX Technologies & Trends', 'Customer Experience', 68),
    ('PROC_DIGITAL', 'Digital Procurement', 'Procurement', 69),
    ('IT_DIGITAL_TECH', 'Digital Technology Knowledge', 'IT', 70),
    ('LOG_DISTRIBUTION', 'Distribution Logistics', 'Logistics', 71),
    ('OPS_DOC_RECORD', 'Documents & Records Management', 'Operations', 72),
    ('FIN_E2E_AUDIT', 'E2E Audit & Reconciliation', 'Finance', 73),
    ('HR_ENGAGEMENT', 'Employee Engagement', 'HR', 74),
    ('HR_PERFORMANCE', 'Employee Performance Management', 'HR', 75),
    ('IT_ENTERPRISE_ARCH', 'Enterprise Architecture', 'IT', 76),
    ('TELCO_TELEPHONY', 'Enterprise Telephony Management', 'Telecom', 77),
    ('SOFT_ENTREPRENEUR', 'Entrepreneurial Mindset', 'Soft Skills', 78),
    ('MKT_EVENTS', 'Events & Sponsorship Management', 'Marketing', 79),
    ('HR_EXPAT', 'Expats Integration & Management', 'HR', 80),
    ('OPS_FACILITIES', 'Facilities Operations and Maintenance', 'Operations', 81),
    ('FIN_ACUMEN', 'Financial Acumen', 'Finance', 82),
    ('FIN_ANALYSIS', 'Financial Analysis', 'Finance', 83),
    ('FIN_REPORTING', 'Financial Reporting & Compliance', 'Finance', 84),
    ('FIN_FIXED_ASSET', 'Fixed Assets Management', 'Finance', 85),
    ('LOG_FORKLIFT', 'Forklift Operation', 'Logistics', 86),
    ('RISK_FRAUD', 'Fraud Management', 'Risk', 87),
    ('FIN_BANKING', 'Funding & Banking Relations', 'Finance', 88),
    ('MKT_GEOMARKETING', 'Geomarketing', 'Marketing', 89),
    ('RISK_GRC', 'Governance Risk & Control', 'Risk', 90),
    ('CORP_GOV_REL', 'Government Relations', 'Corporate', 91),
    ('HR_ANALYTICS', 'HR Analytics', 'HR', 92),
    ('HR_INCENTIVES', 'Incentives Program Management', 'HR', 93),
    ('IT_INCIDENT', 'Incident Management', 'IT Operations', 94),
    ('SEC_COMPLIANCE', 'Information Security Compliance & Audit', 'Security', 95),
    ('SEC_GOVERNANCE', 'Information Security Governance', 'Security', 96),
    ('SEC_SUPPORT', 'Information Security Operation & Support', 'Security', 97),
    ('SEC_RISK', 'Information Security Risk Management', 'Security', 98),
    ('SEC_TOOLS', 'Information Security Systems & Tools', 'Security', 99),
    ('FIN_INSURANCE', 'Insurance Claim Processing', 'Finance', 100),
    ('FIN_INS_POLICY', 'FIN_INS_POLICY', 'Insurance Planning & Policies Development', 101),
    ('MKT_IMC', 'MKT_IMC', 'Integrated Marketing Communication', 102),
    ('NET_DIMENSION', 'NET_DIMENSION', 'Integrated Network Dimensioning', 103),
    ('AUDIT_INTERNAL', 'AUDIT_INTERNAL', 'Internal Audit Planning & Execution', 104),
    ('CORP_INTERNAL_COMM', 'CORP_INTERNAL_COMM', 'Internal Communication Management', 105),
    ('FIN_INTERNAL_CTRL', 'FIN_INTERNAL_CTRL', 'Internal Control', 106),
    ('AUDIT_IPPF', 'AUDIT_IPPF', 'International Professional Practices Framework (IPPF)', 107),
    ('TECH_IOT_M2M', 'TECH_IOT_M2M', 'Internet of Things (and M2M)', 108),
    ('LOG_INVENTORY', 'LOG_INVENTORY', 'Inventory Management & Optimization', 109),
    ('FIN_INVESTMENT', 'FIN_INVESTMENT', 'Investment Evaluation & Management', 110),
    ('IT_PLATFORM_OPS', 'IT_PLATFORM_OPS', 'IT Platforms Operations', 111),
    ('HR_JOB_DESIGN', 'HR_JOB_DESIGN', 'Job Analysis - Design & Evaluation', 112),
    ('SALES_KAM', 'SALES_KAM', 'Key Account Management', 113),
    ('IT_KB', 'IT_KB', 'Knowledge Base Management', 114),
    ('LEGAL_LABOR', 'LEGAL_LABOR', 'Labor Law & Employment Legislation', 115),
    ('CORP_LOBBYING', 'CORP_LOBBYING', 'Lobbying', 116),
    ('LEGAL_DIGITAL', 'LEGAL_DIGITAL', 'Local Digital Laws & Regulations', 117),
    ('COMM_LANGUAGE', 'COMM_LANGUAGE', 'Local Language Knowledge', 118),
    ('LOG_WAREHOUSE', 'LOG_WAREHOUSE', 'Logistics & Warehousing', 119),
    ('DATA_AI_ML', 'DATA_AI_ML', 'Machine Learning - Artificial Intelligence', 120),
    ('FIN_MGMT_REPORT', 'FIN_MGMT_REPORT', 'Management Reporting', 121),
    ('MKT_RESEARCH', 'MKT_RESEARCH', 'Market Research & Study', 122),
    ('MKT_SEGMENT', 'MKT_SEGMENT', 'Market Segmentation', 123),
    ('ENG_MEP', 'ENG_MEP', 'Mechanical - Electrical & Plumbing Knowledge', 124),
    ('MKT_MEDIA', 'MKT_MEDIA', 'Media Planning & Management', 125),
    ('DIG_MEDIA_TECH', 'DIG_MEDIA_TECH', 'Media Technologies', 126),
    ('OPS_MEETING', 'OPS_MEETING', 'Meeting Administration', 127),
    ('COMM_MESSAGE', 'COMM_MESSAGE', 'Message Handling', 128),
    ('TELCO_MFS_SERV', 'TELCO_MFS_SERV', 'MFS Adjacent Services & Products', 129),
    ('TELCO_MFS_TRENDS', 'TELCO_MFS_TRENDS', 'MFS Ecosystem & Trends', 130),
    ('MKT_COMM_EFFECT', 'MKT_COMM_EFFECT', 'Monitoring & Measuring Communication Effectiveness', 131),
    ('SOFT_NEGOTIATION', 'SOFT_NEGOTIATION', 'Negotiation', 132),
    ('NET_ANALYTICS', 'NET_ANALYTICS', 'Network Analytics', 133),
    ('NET_MONITORING', 'NET_MONITORING', 'Network Monitoring', 134),
    ('NET_NOC', 'NET_NOC', 'Network Operations Center (NOC)', 135),
    ('NET_OPTIMIZATION', 'NET_OPTIMIZATION', 'Network Optimization', 136),
    ('NET_PERFORMANCE', 'NET_PERFORMANCE', 'Network Performance Management', 137),
    ('NET_TESTING', 'NET_TESTING', 'Network Testing', 138),
    ('NET_NV', 'NET_NV', 'Network Virtualization (NV)', 139),
    ('DIG_MARKETING', 'DIG_MARKETING', 'Online - Digital Marketing', 140),
    ('SALES_DIGITAL', 'SALES_DIGITAL', 'Online - Digital Sales', 141),
    ('HR_ORG_STRUCT', 'HR_ORG_STRUCT', 'Organizational Structuring', 142),
    ('MKT_OUTDOOR', 'MKT_OUTDOOR', 'Outdoor Advertising Management', 143),
    ('STRAT_PARTNERSHIP', 'STRAT_PARTNERSHIP', 'Partnership Engagement - Execution & Monitoring', 144),
    ('NET_PASSIVE_INFRA', 'NET_PASSIVE_INFRA', 'Passive Infrastructure Deployment', 145),
    ('NET_PASSIVE_OPS', 'NET_PASSIVE_OPS', 'Passive Network Operations', 146),
    ('FIN_PAYROLL', 'FIN_PAYROLL', 'Payroll Process Management', 147),
    ('ANALYTICS_DASHBOARD', 'ANALYTICS_DASHBOARD', 'Performance Dashboard Design & Development', 148),
    ('HR_PERF_REPORT', 'HR_PERF_REPORT', 'Performance Management & Reporting', 149),
    ('HR_MEASURE_REPORT', 'HR_MEASURE_REPORT', 'Performance Measurement & Reporting', 150),
    ('FIN_BUDGETING', 'FIN_BUDGETING', 'Planning & Budgeting', 151),
    ('SOFT_PROBLEM_SOLV', 'SOFT_PROBLEM_SOLV', 'Problem Solving', 152),
    ('PM_PORTFOLIO', 'PM_PORTFOLIO', 'Product - Portfolio Strategy Development', 153),
    ('PM_PRODUCT_DEV', 'PM_PRODUCT_DEV', 'Product Development', 154),
    ('PM_LIFECYCLE', 'PM_LIFECYCLE', 'Product Portfolio & Lifecycle Management', 155),
    ('PM_PROJECT', 'PM_PROJECT', 'Project Management', 156),
    ('TELCO_PROTOCOL', 'TELCO_PROTOCOL', 'Protocol Service Knowledge', 157),
    ('MKT_PR', 'MKT_PR', 'Public Relations', 158),
    ('QUALITY_QMS', 'QUALITY_QMS', 'QMS Implementation & Maintenance', 159),
    ('LEGAL_REG_ECO', 'LEGAL_REG_ECO', 'Regulatory Economics', 160),
    ('FIN_R2P', 'FIN_R2P', 'Request to Pay Process (R2P)', 161),
    ('SALES_RETAIL', 'SALES_RETAIL', 'Retail Sales Operations', 162),
    ('CX_LOYALTY', 'CX_LOYALTY', 'Retention & Loyalty Program Management', 163),
    ('FIN_REV_ASSURANCE', 'FIN_REV_ASSURANCE', 'Revenue Assurance Systems & Tools', 164),
    ('FIN_REV_CYCLE', 'FIN_REV_CYCLE', 'Revenue Cycle Management', 165),
    ('FIN_REV_LEAK', 'FIN_REV_LEAK', 'Revenue Leakage Control', 166),
    ('HR_REWARD', 'HR_REWARD', 'Reward Management', 167),
    ('RISK_APPETITE', 'RISK_APPETITE', 'Risk Appetite Framework Management', 168),
    ('RISK_IDENTIFY', 'RISK_IDENTIFY', 'Risk Identification & Assessment', 169),
    ('RISK_MGMT', 'RISK_MGMT', 'Risk Management', 170),
    ('RISK_POLICY', 'RISK_POLICY', 'Risk Management Policy & Procedures', 171),
    ('RISK_RESPONSE', 'RISK_RESPONSE', 'Risk Response & Reporting', 172),
    ('LOG_ROUTE', 'LOG_ROUTE', 'Route Planning & Traffic Regulations', 173),
    ('OPS_SAFETY', 'OPS_SAFETY', 'Safety Management', 174),
    ('SALES_ANALYTICS', 'SALES_ANALYTICS', 'Sales & Distribution Analytics', 175),
    ('SALES_AUTO', 'SALES_AUTO', 'Sales Automation', 176),
    ('SALES_FULFILL', 'SALES_FULFILL', 'Sales Fulfillment', 177),
    ('SALES_TRAIN', 'SALES_TRAIN', 'Sales Training', 178),
    ('OPS_RESOURCES', 'OPS_RESOURCES', 'Scarce Resources Management', 179),
    ('SEC_PLANNING', 'SEC_PLANNING', 'Security Planning', 180),
    ('TELCO_SERVICE_QA', 'TELCO_SERVICE_QA', 'Service Assurance & Quality', 181),
    ('TELCO_SERVICE_CFG', 'TELCO_SERVICE_CFG', 'Service Configuration & Activation Process', 182),
    ('TELCO_DELIVERY', 'TELCO_DELIVERY', 'Service Delivery Networks', 183),
    ('TELCO_SERVICE_MON', 'TELCO_SERVICE_MON', 'Service Quality Monitoring & Compliance', 184),
    ('IT_SERVICE', 'IT_SERVICE', 'Service-Orientated IT', 185),
    ('IT_SERVICES_INT', 'IT_SERVICES_INT', 'Services Integration', 186),
    ('OPS_SHARED_SERV', 'OPS_SHARED_SERV', 'Shared Services Management', 187),
    ('COM_SMART_PRICE', 'COM_SMART_PRICE', 'Smart Pricing', 188),
    ('MKT_SOCIAL_MEDIA', 'MKT_SOCIAL_MEDIA', 'Social Media Management', 189),
    ('DATA_STATS', 'DATA_STATS', 'Statistics', 190),
    ('STRAT_FORMULATION', 'STRAT_FORMULATION', 'Strategy Formulation', 191),
    ('STRAT_IMPLEMENT', 'STRAT_IMPLEMENT', 'Strategy Implementation', 192),
    ('HR_SUCCESSION', 'HR_SUCCESSION', 'Succession Planning', 193),
    ('PROC_SUPPLIER_NEG', 'PROC_SUPPLIER_NEG', 'Supplier Negotiation & Deal Closing', 194),
    ('PROC_CONTRACTS', 'PROC_CONTRACTS', 'Suppliers & Contracts Management', 195),
    ('PROC_MARKET', 'PROC_MARKET', 'Supply Market Analysis', 196),
    ('IT_SYS_INT', 'IT_SYS_INT', 'Systems Integration', 197),
    ('HR_TALENT_ASSESS', 'HR_TALENT_ASSESS', 'Talent Assessment', 198),
    ('HR_CAPABILITY', 'HR_CAPABILITY', 'Talent Capability Building', 199),
    ('HR_TALENT_ACQ', 'HR_TALENT_ACQ', 'Talent Market Intelligence & Acquisition', 200),
    ('FIN_TAX_AUDIT', 'FIN_TAX_AUDIT', 'Tax Audit & Planning', 201),
    ('FIN_TAX_RETURN', 'FIN_TAX_RETURN', 'Tax Return Preparation', 202),
    ('LEGAL_TAX', 'LEGAL_TAX', 'Taxation Law', 203),
    ('TELCO_WHOLESALE', 'TELCO_WHOLESALE', 'Technical Aspects of Wholesale', 204),
    ('ENG_TECH_SPEC', 'ENG_TECH_SPEC', 'Technical Specifications Development', 205),
    ('COMM_TECH_WRITE', 'COMM_TECH_WRITE', 'Technical Writing and Reporting', 206),
    ('TELCO_MARKET', 'TELCO_MARKET', 'Telecom Market & Industry Knowledge', 207),
    ('TELCO_REG_POLICY', 'TELCO_REG_POLICY', 'Telecom Regulatory Policy', 208),
    ('MKT_TRADE', 'MKT_TRADE', 'Trade Marketing', 209),
    ('HR_TRAINING', 'HR_TRAINING', 'Training Management & Facilitation', 210),
    ('FIN_ACC_CLOSING', 'FIN_ACC_CLOSING', 'Transactional Accounting & Closing', 211),
    ('COMM_TRANSLATION', 'COMM_TRANSLATION', 'Translation & Interpretation', 212),
    ('NET_TRANSPORT', 'NET_TRANSPORT', 'Transport Network Design & Planning', 213),
    ('LOG_FLEET', 'LOG_FLEET', 'Transportation & Fleet Management', 214),
    ('OPS_TRAVEL', 'OPS_TRAVEL', 'Travel Planning & Assistance', 215),
    ('FIN_TREASURY', 'FIN_TREASURY', 'Treasury Policies & Risk', 216),
    ('IT_TROUBLESHOOT', 'IT_TROUBLESHOOT', 'Troubleshooting & Technical Problem Solving', 217),
    ('IT_UAT', 'IT_UAT', 'User Acceptance Testing (UAT)', 218),
    ('DIG_WEBSITE', 'DIG_WEBSITE', 'Website Management', 219),
    ('TELCO_WHOLESALE_REG', 'TELCO_WHOLESALE_REG', 'Wholesale Access Regulations', 220),
    ('HR_WORKFORCE', 'HR_WORKFORCE', 'Workforce Management', 221),
]

# (code, name)
ESTABLISHMENTS: list[tuple[str, str]] = [
    ('UBO', 'Université de Bouira – Akli Mohand Oulhadj'),
    ('UDJ', 'Université de Djelfa – Ziane Achour'),
    ('UGH', 'Université de Ghardaia'),
    ('UKM', 'Université de Khemis Miliana – Djilali Bounaama'),
    ('UMD', 'Université Médéa – Yahia Farès'),
    ('USTHB', "Université des sciences et de la technologie d'Alger, Houari Boumediène"),
    ('UBJ', 'Université de Béjaia – Abderrahmane Mira'),
    ('UBM', 'Université de Boumerdès – M’hamed Bougara'),
    ('UTO', 'Université de Tizi Ouzou – Mouloud Maameri'),
    ('ULG', 'Université de Laghouat – Amar Telidji'),
    ('UBL1', 'Université Blida 1 – Saad Dahlab'),
    ('UBL2', 'Université de Blida 2 – Lounici Ali'),
    ('UJ', 'Université de Jijel – Mohammed Seddik Ben yahia'),
    ('UTB', 'Université de Tébessa – Larbi Tébessi'),
    ('UBBA', 'Université de Bordj Bou Arréridj – Mohamed Bachir El Ibrahimi'),
    ('UET', "Université d'El Tarf – Chadli Bendjedid"),
    ('UKH', 'Université de Khenchela – Abbas Laghrour'),
    ('UOEB', "Université de Oum El Bouaghi – Larbi Ben M'hidi"),
    ('UEL', "Université d'El Oued – Hamma Lakhdar"),
    ('USA', 'Université de Souk Ahras – Mohammed-Chérif Messaadia'),
    ('UBC', 'Université de Béchar – Mohamed Tahri'),
    ('UMA', 'Université de Mascara – Mustapha Stambouli'),
    ('USA_2', 'Université de Saida – Tahar Moulay'),
    ('UTL', 'Université de Tlemcen – Abou Bekr Belkaid'),
    ('UAD', "Université d'Adrar – Ahmed Draya"),
    ('UTI', 'Université de Tiaret – Ibn Khaldoun'),
    ('USBA', 'Université Sidi Bel Abbès – Djillali Liabes'),
    ('UMOS', 'Université de Mostaganem – Abdelhamid Ibn Badis'),
    ('UOR1', "Université d'Oran 1 – Ahmed Ben Bella"),
    ('USTO', "Université des sciences et de la technologie d'Oran – Mohamed Boudiaf"),
    ('UOR2', "Université d'Oran 2 – Mohamed Ben Ahmed"),
    ('UCH', 'Université de Chlef – Hassiba Benbouali'),
    ('UTI_2', 'Université de Tissemsilt'),
    ('UAT', 'Université de Aïn Témouchent'),
    ('UREL', 'Université de Relizane'),
    ('ENPC', 'École nationale polytechnique de Constantine'),
    ('ENSCF', 'École nationale supérieure de comptabilité et de finance de Constantine'),
    ('ENSB', 'École nationale supérieure de biotechnologie de Constantine'),
    ('ENSMM', "École nationale supérieure des mines et métallurgie d'Annaba"),
    ('ENSTI', "École nationale supérieure de technologies industrielles d'Annaba"),
    ('ENSGG', "École nationale supérieure des sciences de gestion d'Annaba"),
    ('ENP', 'École nationale polytechnique'),
    ('ENSA', 'École nationale supérieure agronomique'),
    ('ENSI', "École nationale supérieure d'informatique"),
    ('EPAU', "École polytechnique d'architecture et d'urbanisme"),
    ('ENSTA', "École nationale supérieure de technologie d'Alger"),
    ('ESC', 'École supérieure de commerce'),
    ('EHEC', "École des hautes études commerciales (EHEC) d'Alger"),
    ('ESSTIN', "École supérieure en sciences et technologies de l'informatique et du numérique de Béjaia"),
    ('ENSNN', 'École nationale supérieure des nanosciences et nanotechnologie'),
    ('ENSSA', 'École nationale supérieure des systèmes autonomes'),
    ('ENSTP', 'École nationale supérieure des travaux publics'),
    ('ENSSAA', "École nationale supérieure des sciences de l'aliment et des industries agroalimentaires d'Alger"),
    ('ENSML', "École nationale supérieure en sciences de la mer et de l'aménagement du littoral d'Alger"),
    ('ENSV', 'École nationale supérieure vétérinaire'),
    ('ENSSAE', 'École nationale supérieure en statistique et en économie appliquée'),
    ('ENSM', 'École nationale supérieure de management'),
    ('ENSJSI', "École nationale supérieure de journalisme et des sciences de l'information"),
    ('ENPO', "École nationale polytechnique d'Oran"),
    ('ESGEE', "École supérieure en génie électrique et énergétique d'Oran"),
    ('ENSEO', "École nationale supérieure d'économie d'Oran"),
    ('ENSSBO', "École nationale supérieure des sciences biologiques d'Oran"),
    ('ENSMT', 'École nationale supérieure de management de Tlemcen'),
    ('ENSSA_TL', 'École nationale supérieure des sciences appliquées de Tlemcen'),
    ('ENSI_SBA', "École nationale supérieure d'informatique de Sidi Bel Abbés"),
    ('ENSA_M', 'École nationale supérieure agronomique de Mostaganem'),
    ('ENSTTIC', "École nationale supérieure des télécommunications et technologies de l'information et de la communication d'Oran"),
]

# (code, name)
LANGUAGES: list[tuple[str, str]] = [
    ('dz', 'Arabe'),
    ('fr', 'Français'),
    ('en', 'Anglais'),
    ('es', 'Espagnol'),
    ('de', 'Allemand'),
]


_skills_tbl = sa.table(
    "skillconnect_skills",
    sa.column("code", sa.String),
    sa.column("name", sa.String),
    sa.column("category", sa.String),
    sa.column("external_id", sa.Integer),
)
_estab_tbl = sa.table(
    "skillconnect_establishments",
    sa.column("code", sa.String),
    sa.column("name", sa.String),
)
_lang_tbl = sa.table(
    "skillconnect_languages",
    sa.column("code", sa.String),
    sa.column("name", sa.String),
)


def upgrade() -> None:
    conn = op.get_bind()

    for code, name, category, external_id in SKILLS:
        stmt = pg_insert(_skills_tbl).values(
            code=code, name=name, category=category, external_id=external_id
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["code"],
            set_=dict(
                name=stmt.excluded.name,
                category=stmt.excluded.category,
                external_id=stmt.excluded.external_id,
            ),
        )
        conn.execute(stmt)

    for code, name in ESTABLISHMENTS:
        stmt = pg_insert(_estab_tbl).values(code=code, name=name)
        stmt = stmt.on_conflict_do_update(
            index_elements=["code"], set_=dict(name=stmt.excluded.name)
        )
        conn.execute(stmt)

    for code, name in LANGUAGES:
        stmt = pg_insert(_lang_tbl).values(code=code, name=name)
        stmt = stmt.on_conflict_do_update(
            index_elements=["code"], set_=dict(name=stmt.excluded.name)
        )
        conn.execute(stmt)


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        _skills_tbl.delete().where(
            _skills_tbl.c.code.in_([c for c, *_ in SKILLS])
        )
    )
    conn.execute(
        _estab_tbl.delete().where(
            _estab_tbl.c.code.in_([c for c, _ in ESTABLISHMENTS])
        )
    )
    conn.execute(
        _lang_tbl.delete().where(
            _lang_tbl.c.code.in_([c for c, _ in LANGUAGES])
        )
    )
