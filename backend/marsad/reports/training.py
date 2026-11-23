"""الوضع التدريبي: تمارين تحقق بتصحيح آلي، والحل النموذجي يُعرض بعد الإجابة فقط. تصحيح المدرّب يتقدّم على الآلي."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from marsad.engines.prompts import EVIDENCE_GRADES, VERDICT_LABELS
from marsad.models import User
from marsad.models.reports import Exercise, Submission
from marsad.text import normalize_ar

WEIGHTS = {"label": 50, "grade": 25, "reasoning": 25}

# تمارين أولى بمواد مصطنعة (أسماء وجهات خيالية)، يضيف المدرّب غيرها بمواد حقيقية.
SEED = [
    {"title": "صورة «فيضان اليوم» في وسط المدينة", "level": "مبتدئ",
     "instructions": "منشور متداول يقول إن الصورة التُقطت صباح اليوم. افحص المعطيات واحكم.",
     "material": {"text": "منشور على صفحة «أخبار المدينة الآن» (اليوم 09:10): «شاهد الفيضان الذي أغرق شارع السوق صباح اليوم!» مع صورة لشارع غارق بالمياه.\n\n"
                          "نتيجة المختبر: البصمة الإدراكية للصورة تطابق صورة في أرشيفنا رُصدت قبل أربع سنوات على موقع إخباري، بفرق 3 من 64. "
                          "البيانات الوصفية محذوفة. لا توقيع C2PA.\n\nنشرة الأرصاد اليوم: لا أمطار في المدينة منذ أسبوعين."},
     "answer": {"label": "مضلل", "grade": "قاطع", "key_points": ["أرشيف|نسخه اقدم|قبل اربع سنوات", "الارصاد|لا امطار", "البيانات الوصفيه|لا يكفي"],
                "explanation": "الصورة حقيقية لكنها قديمة: نسخة أقدم في الأرشيف قبل التاريخ المدّعى (دليل قاطع)، ونشرة الأرصاد تنفي أمطار اليوم. "
                               "غياب البيانات الوصفية لا يدل على شيء وحده."}},
    {"title": "تصريح منسوب إلى «وزير الموارد» في مملكة خيالية", "level": "متوسط",
     "instructions": "اقتباس ينتشر على المنصات. هل قاله الوزير؟",
     "material": {"text": "منشور متداول: «قال وزير الموارد سليم الفارس إن المياه ستُقطع عن كل المحافظات لمدة شهر».\n\n"
                          "البحث في الرصد: لا موقع إخباري ولا حساب رسمي نشر التصريح. أقدم ظهور له حساب أُنشئ قبل يومين، ونشرته 6 حسابات بالنص نفسه خلال 20 دقيقة.\n\n"
                          "بيان الوزارة الرسمي (اليوم 11:00): «لا صحة لما نُسب إلى الوزير، ولا انقطاع مخطط للمياه»."},
     "answer": {"label": "مفبرك", "grade": "قاطع", "key_points": ["بيان|نفت|لا صحه", "لا مصدر|لم ينشر|لا موقع", "حسابات|منسق|نسخ"],
                "explanation": "لا أصل للتصريح في أي مصدر موثوق، والوزارة نفته ببيان رسمي (قاطع). انتشاره بنص واحد من حسابات حديثة مؤشر على حملة منسّقة."}},
    {"title": "نسبة البطالة «30٪»", "level": "متوسط",
     "instructions": "عنوان في موقع إخباري. قارن بالرقم الرسمي.",
     "material": {"text": "عنوان: «البطالة تقفز إلى 30٪ هذا العام».\n\nدائرة الإحصاءات (الربع الأخير): البطالة العامة 22٪، وبين الشباب 31٪.\n\n"
                          "المتن ينقل رقم الشباب دون أن يذكر أنه خاص بفئة عمرية."},
     "answer": {"label": "صحيح جزئيًا", "grade": "مؤشر قوي", "key_points": ["الشباب|فئه", "22", "العنوان|عمم|تعميم"],
                "explanation": "الرقم حقيقي لكنه لفئة الشباب (31٪)، والعنوان عمّمه على الجميع (22٪). الحكم «صحيح جزئيًا»."}},
]


def seed(db: Session) -> int:
    if db.scalar(select(func.count()).select_from(Exercise)):
        return 0
    for e in SEED:
        db.add(Exercise(**e))
    db.flush()
    return len(SEED)


def validate_answer(a: dict) -> dict:
    if a.get("label") not in VERDICT_LABELS or a.get("grade") not in EVIDENCE_GRADES:
        raise ValueError("اختر الحكم ودرجة الدليل من القائمة")
    kp = [k.strip() for k in a.get("key_points", []) if k.strip()]
    return {"label": a["label"], "grade": a["grade"], "key_points": kp, "explanation": (a.get("explanation") or "").strip()}


def grade(ex: Exercise, response: dict) -> tuple[float, dict]:
    ans = ex.answer
    fb: dict = {}
    score = 0.0
    if response.get("label") == ans["label"]:
        score += WEIGHTS["label"]
        fb["label"] = "الحكم صحيح."
    else:
        fb["label"] = f"الحكم «{response.get('label') or '—'}» والصحيح «{ans['label']}»."
    if response.get("grade") == ans["grade"]:
        score += WEIGHTS["grade"]
        fb["grade"] = "درجة الدليل صحيحة."
    else:
        fb["grade"] = f"درجة الدليل «{response.get('grade') or '—'}» والصحيحة «{ans['grade']}»."
    text = normalize_ar(response.get("reasoning", ""))
    pts = ans.get("key_points") or []
    hit = [p for p in pts if any(normalize_ar(alt) and normalize_ar(alt) in text for alt in p.split("|"))]
    if pts:
        score += WEIGHTS["reasoning"] * len(hit) / len(pts)
    fb["reasoning"] = f"ذكرت {len(hit)} من {len(pts)} نقاط أساسية في التعليل."
    fb["missed"] = [p.split("|")[0] for p in pts if p not in hit]
    return round(score, 1), fb


def submit(db: Session, user: User, ex: Exercise, response: dict) -> Submission:
    n = db.scalar(select(func.count()).select_from(Submission).where(Submission.exercise_id == ex.id, Submission.user_id == user.id)) or 0
    score, fb = grade(ex, response)
    s = Submission(exercise_id=ex.id, user_id=user.id, attempt=n + 1, response=response, score=score, feedback=fb)
    db.add(s)
    db.flush()
    return s


def final_score(s: Submission) -> float:
    return s.trainer_score if s.trainer_score is not None else s.score
