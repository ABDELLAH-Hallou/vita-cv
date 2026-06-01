I am applying for a role. Please use the `skills/job-description-analyzer.md` skill to analyze my current CV in `main.tex` and the job description below. Tell me my match score and what critical keywords or experiences I am missing.

If multiple job descriptions are provided, produce ONE unified cross-role analysis:
- Identify keywords and requirements that appear across multiple jobs and weight them higher.
- Identify role-specific keywords separately.
- Compute a match score for each job.
- Compute an overall match probability across all jobs.
- Recommend the highest-leverage CV changes that improve fit across the full set of roles.

**IMPORTANT INSTRUCTION**: 
Please save your full analysis report to a new file at `results/analysis.md` so that the next steps in my workflow can read it.

-----------------------------------------
JOB DESCRIPTION:
{{JOB_DESCRIPTION}}
