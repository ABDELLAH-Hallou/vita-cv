Based on the gaps we identified for this role, please use the `skills/tech-resume-optimizer.md`, `skills/resume-bullet-writer.md`, `skills/resume-ats-optimizer.md` and `skills/resume-tailor.md` skills to rewrite the CV title/headline, professional summary, experience, and skills sections in my `main.tex` file. 

Instructions:
1. READ `results/analysis.md` to understand the exact gaps and keywords we need to target. 
2. Rewrite the CV title/headline as exactly one role name, such as `Applied AI Engineer`, `Data Engineer`, `Software Engineer`, or `ML Engineer`. Do not append taglines, specializations, technology lists, or additional roles with pipes, slashes, dashes, or ampersands. For example, replace `Applied AI Engineer | Production AI Agents & Enterprise AI Systems` with `Applied AI Engineer`. Put relevant specialization keywords in the summary or skills instead, even if the existing CV or analysis recommends an expanded title.
3. Rewrite the professional summary to mirror the job's most important requirements while staying truthful.
4. Optimize the bullet points using the XYZ formula, but keep them EXTREMELY concise (maximum 1 line, strip all fluff/bloat).
5. Naturally weave in the required keywords from the job description below without sounding bloated.
6. Bold key tools and technologies mentioned in the bullet points (e.g., `\textbf{Python}`, `\textbf{LangGraph}`) to enhance scannability.
7. Keep `main.tex` structurally identical; only update existing content strings and existing title/summary fields or sections.
8. Save a high-level summary of the edits you made into a new file at `results/adapt.md`.

If multiple job descriptions are provided, produce ONE optimized CV, not separate CV versions:
- Prioritize skills, keywords, and bullet points that match 2 or more jobs.
- Choose a single role name for the title/headline that best fits the shared requirements and the candidate's experience; do not combine role names or append a shared-theme tagline.
- Write the summary for the shared profile the company is most likely to value.
- Use role-specific keywords only when they strengthen the general CV without making it bloated.
- Keep the CV coherent, concise, and credible across all listed roles.
- Maximize overlap with the shared requirements from the full set of jobs.

-----------------------------------------
JOB DESCRIPTION:
{{JOB_DESCRIPTION}}
