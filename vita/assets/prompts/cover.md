Use the `skills/cover-letter-generator.md` skill to write one tailored cover letter (lettre de motivation) based on the candidate's current `main.tex` and the job description below.

Instructions:
1. Read the current CV, including its local LaTeX input files. If an analysis exists at `.vita/results/analyze.md`, use it to prioritize relevant experience, not as evidence of new candidate facts.
2. Explain the connection between the candidate's actual experience and the employer's needs in clear, natural prose. Select one or two relevant examples instead of repeating the CV or listing technologies.
3. Use only candidate facts supported by captured CV sources or explicitly verified knowledge spans. Unverified `.vita/cv.yaml` content is context, never evidence. Use `job.md` for employer and role requirements, never as proof that the candidate has those qualifications. Do not invent metrics, connections, company news, motivations, contact details, or qualifications. Omit unknown recipient details and use a neutral salutation when needed. Do not leave placeholders.
4. Write a concise business letter of 3–4 paragraphs, aiming for one page. Include the candidate's known contact information, date, appropriate salutation, and sign-off. For multiple jobs at the same company, write one coherent letter about the shared role requirements, not separate letters or an enumeration of job titles.
5. Create a complete standalone LaTeX document at `cover-letter.tex`. Use a standard `article` or `letter` class, UTF-8 text, and packages compatible with pdfLaTeX. Escape LaTeX special characters in prose and preserve accents. Do not depend on the CV's custom class, macros, images, or external files. Do not modify the CV.
6. Save a brief account of the choices made to `.vita/results/cover.md`.

-----------------------------------------
JOB DESCRIPTION:
{{JOB_DESCRIPTION}}
