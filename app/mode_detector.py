EXECUTOR_KEYWORDS = [
    "วันนี้", "พรุ่งนี้", "deadline", "ต้องทำ", "remind", "ยังไม่ได้",
    "ค้างอยู่", "รีบ", "urgent", "ด่วน", "สิ้นเดือน", "เดือนนี้",
    "อาทิตย์นี้", "เร็วๆ นี้", "ก่อน", "ทัน",
    "today", "tomorrow", "due", "pending", "asap", "overdue", "soon",
]

PLANNER_KEYWORDS = [
    "แผน", "strategy", "ภาพรวม", "priority", "สำคัญ", "เป้าหมาย",
    "roadmap", "ทิศทาง", "focus", "quarter", "q1", "q2", "q3", "q4",
    "ระยะยาว", "วางแผน", "กลยุทธ์",
    "plan", "overview", "goal", "milestone", "strategic", "prioritize",
]

RESEARCHER_KEYWORDS = [
    "เคยจด", "เคยคิด", "เกี่ยวกับ", "หาข้อมูล", "อ่านว่า", "รู้ว่า",
    "ไอเดีย", "คิดว่า", "note เรื่อง", "บันทึก",
    "what did i", "tell me about", "find", "search", "idea", "thought",
    "note about", "wrote", "mentioned",
]

# bug #6 fix: explicit priority order เมื่อ tie
MODE_PRIORITY = ["executor", "planner", "researcher"]

def detect_mode(query: str, explicit_mode: str = None) -> tuple[str, str]:
    if explicit_mode and explicit_mode != "balanced":
        return explicit_mode, "explicit"

    q = query.lower()

    scores = {
        "executor":   sum(1 for kw in EXECUTOR_KEYWORDS if kw in q),
        "planner":    sum(1 for kw in PLANNER_KEYWORDS if kw in q),
        "researcher": sum(1 for kw in RESEARCHER_KEYWORDS if kw in q),
    }

    max_score = max(scores.values())
    if max_score > 0:
        # tie-breaking: เลือกตาม priority order
        for mode in MODE_PRIORITY:
            if scores[mode] == max_score:
                return mode, f"keyword match (score={max_score})"

    return "balanced", "default"