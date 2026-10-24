"""Content-free excerpt captured from ChatGPT history on 2026-10-24.

Identifiers and exchanges are anonymized. Each segment stops at its nearest
user. Roles, timestamps, recipients and end-turn flags are preserved. All
records used gpt-6-pro and finished_successfully, without visual hiding.
"""

CAPTURED_NODES: list[tuple[int, int | None, str, float, bool | None, str]] = [
    (0, None, "user", 1792827123.221903, None, "all"),
    (1, 0, "assistant", 1792827123.699473, False, "container.exec"),
    (2, 1, "tool", 1792827123.809645, None, "all"),
    (3, 2, "assistant", 1792827125.93116, False, "all"),
    (4, 3, "assistant", 1792827125.935079, False, "all"),
    (5, 4, "assistant", 1792827147.490684, False, "all"),
    (6, 5, "assistant", 1792827153.486731, False, "all"),
    (7, 6, "assistant", 1792827164.656145, False, "all"),
    (8, 7, "assistant", 1792827174.614245, False, "all"),
    (9, 8, "assistant", 1792827185.77061, False, "all"),
    (10, 9, "assistant", 1792827197.298061, False, "all"),
    (11, 10, "assistant", 1792827222.287581, False, "all"),
    (12, 11, "assistant", 1792827237.636578, False, "all"),
    (13, 12, "assistant", 1792827246.38681, False, "api_tool.call_tool"),
    (14, 13, "tool", 1792827250.947466, None, "all"),
    (15, 14, "assistant", 1792827256.270362, False, "all"),
    (16, 15, "assistant", 1792827256.489383, False, "container.exec"),
    (17, 16, "tool", 1792827256.613839, None, "all"),
    (18, 17, "assistant", 1792827258.428864, False, "all"),
    (19, 18, "assistant", 1792827270.764114, False, "all"),
    (20, 19, "assistant", 1792827281.891928, False, "container.exec"),
    (21, 20, "tool", 1792827282.005311, None, "all"),
    (22, 21, "assistant", 1792827283.736384, False, "container.exec"),
    (23, 22, "tool", 1792827284.055833, None, "all"),
    (24, 23, "assistant", 1792827316.175074, False, "container.exec"),
    (25, 24, "tool", 1792827316.288327, None, "all"),
    (26, 25, "assistant", 1792827327.168924, False, "all"),
    (27, 26, "assistant", 1792827339.511889, False, "all"),
    (28, 27, "assistant", 1792827339.516825, False, "all"),
    (29, 28, "assistant", 1792827339.529985, True, "all"),
    (30, None, "user", 1792827570.989755, None, "all"),
    (31, 30, "assistant", 1792827572.054042, False, "all"),
    (32, 31, "assistant", 1792827588.985158, False, "all"),
    (33, 32, "assistant", 1792827590.790785, False, "all"),
    (34, 33, "assistant", 1792827590.805716, False, "all"),
    (35, 34, "assistant", 1792827630.855292, True, "all"),
]
