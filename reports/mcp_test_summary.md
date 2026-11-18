# MCP test: with vs without the Data Commons MCP server

Model: `gemini/gemini-3.5-flash-lite`. Prompts: 10. Nudge system prompt: off.

| | cold (no tools) | mcp (Data Commons tools) |
|---|---|---|
| Correct | 4/10 (40%) | 8/10 (80%) |
| Correct or Close | 4/10 (40%) | 8/10 (80%) |
| Wrong | 5/10 (50%) | 2/10 (20%) |
| No number | 1/10 (10%) | 0/10 (0%) |
| Latest year given | 4/10 (40%) | 3/10 (30%) |
| Primary source | 5/10 (50%) | 9/10 (90%) |
| Called a tool | 0/10 (0%) | 10/10 (100%) |
| Used the tool's number (of answers that called a tool) | - | 10/10 (100%) |
| Tool returned a value within the Close cutoff of UNICEF's | - | 8/10 (80%) |
| Avg tool calls | 0.0 | 3.0 |
| Input tokens (total) | 250 | 136,626 |
| Output tokens (total) | 1,748 | 2,145 |
| Cost (total) | $0.0044 | $0.0403 |
| Avg seconds per answer | 1.1 | 11.7 |
| Errors | 0 | 0 |

## Per prompt

| ID | cold score | mcp score | mcp tools called | used tool number | official |
|---|---|---|---|---|---|
| N1 | Wrong (24) | Correct (28.8) | search_indicators; get_observations | Y | 30.498 |
| R1 | Correct (39) | Correct (38) | search_indicators; get_observations | Y | 39.654 |
| P1 | Correct (107) | Correct (107.2) | search_indicators; get_observations | Y | 115.6 |
| T1-5 | No number () | Wrong (74) | search_indicators; search_indicators; get_observations; get_observations | Y | 49 |
| P2 | Wrong (54) | Wrong (60) | search_indicators; get_observations; search_indicators; search_indicators | Y | 67 |
| N5 | Wrong (42.5) | Correct (34) | search_indicators; get_observations; get_observations; get_observations; search_indicators; get_observations; search_indicators | Y | 33.57 |
| T2-1 | Correct (8) | Correct (8.2) | search_indicators; get_observations | Y | 8.23 |
| T2-3 | Wrong (25) | Correct (5.5) | search_indicators; get_observations | Y | 5.5 |
| T3-1 | Wrong (18) | Correct (37.7) | search_indicators; get_observations; get_observations | Y | 38.7 |
| T3-2 | Correct (33.1) | Correct (27.7) | search_indicators; get_observations | Y | 29.9 |