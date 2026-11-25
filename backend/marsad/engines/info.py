"""بطاقات تعريف المزوّدين: ما هو، وما يحتاجه، وكلفته، وخصوصيته — تُعرض قبل الإضافة أو التفعيل.

الأسعار وأسماء النماذج تتغير كل بضعة أشهر، فلا تُكتب هنا: النماذج تُجلب حيّة من المزوّد بمفتاحك،
والأسعار من صفحة المزوّد (الرابط في البطاقة)، ويُدخَل السعر في المحرك ليحسب البرنامج الكلفة ويُطبّق حدّ الإنفاق.
"""

PROVIDER_INFO = {
    "local": {
        "title": "محلي مدمج (مجاني)",
        "what": "نماذج مفتوحة المصدر تعمل داخل البرنامج على جهازك عبر llama.cpp. تختار النموذج من القائمة فيُنزَّل من نسختك على Hugging Face.",
        "needs": ["تنزيل النموذج مرة واحدة (من 1.3 إلى 22 غيغابايت حسب النموذج)", "ذاكرة كافية؛ بطاقة رسوم تسرّعه كثيرًا"],
        "cost": "مجاني تمامًا",
        "privacy": "النص لا يغادر جهازك",
        "internet": "عند التنزيل فقط",
        "quality": "جيدة إلى ممتازة حسب حجم النموذج؛ أبطأ من المدفوعة على جهاز عادي",
        "key_url": "", "pricing_url": "", "docs_url": "https://github.com/ggml-org/llama.cpp",
    },
    "anthropic": {
        "title": "Claude (Anthropic)",
        "what": "نماذج Claude: Haiku (سريع واقتصادي)، Sonnet (متوازن)، Opus (الأقوى). قوية في العربية والتحليل والالتزام بالتعليمات.",
        "needs": ["مفتاح API من حساب Anthropic مع رصيد مدفوع مسبقًا", "اتصال بالإنترنت"],
        "cost": "مدفوع حسب الاستعمال (لكل مليون رمز)؛ تختلف الأسعار بين النماذج",
        "privacy": "يُرسل النص إلى خوادم Anthropic (لا يُستعمل في التدريب حسب سياستها للواجهة البرمجية)",
        "internet": "دائمًا",
        "quality": "من الأعلى في التحليل والكتابة العربية",
        "key_url": "https://console.anthropic.com/settings/keys", "pricing_url": "https://www.anthropic.com/pricing#api",
        "docs_url": "https://docs.claude.com",
    },
    "openai": {
        "title": "OpenAI (GPT)",
        "what": "نماذج GPT من OpenAI بأحجام مختلفة، من الاقتصادية إلى نماذج الاستدلال.",
        "needs": ["مفتاح API من platform.openai.com مع وسيلة دفع أو رصيد", "اتصال بالإنترنت"],
        "cost": "مدفوع حسب الاستعمال (لكل مليون رمز)؛ تختلف الأسعار بين النماذج",
        "privacy": "يُرسل النص إلى خوادم OpenAI (لا يُستعمل في التدريب افتراضيًا للواجهة البرمجية)",
        "internet": "دائمًا",
        "quality": "عالية؛ نماذج الاستدلال أقوى وأغلى وأبطأ",
        "key_url": "https://platform.openai.com/api-keys", "pricing_url": "https://openai.com/api/pricing/",
        "docs_url": "https://platform.openai.com/docs",
    },
    "gemini": {
        "title": "Google Gemini",
        "what": "نماذج Gemini من Google: Flash (سريع واقتصادي) وPro (الأقوى). سياق طويل جدًا يناسب الوثائق الكبيرة.",
        "needs": ["مفتاح من Google AI Studio", "اتصال بالإنترنت"],
        "cost": "فئة مجانية محدودة، ثم مدفوع حسب الاستعمال",
        "privacy": "يُرسل النص إلى Google؛ في الفئة المجانية قد يُستعمل لتحسين الخدمة حسب شروطها",
        "internet": "دائمًا",
        "quality": "عالية، وممتاز للوثائق الطويلة",
        "key_url": "https://aistudio.google.com/app/apikey", "pricing_url": "https://ai.google.dev/pricing",
        "docs_url": "https://ai.google.dev/gemini-api/docs",
    },
    "openai_compatible": {
        "title": "مزوّد متوافق مع OpenAI",
        "what": "أي خدمة أو خادم يتبع واجهة OpenAI (مثل خادم vLLM في مؤسستك، أو مزوّدات نماذج مفتوحة عبر الإنترنت).",
        "needs": ["عنوان الخدمة", "مفتاح إن طلبته الخدمة"],
        "cost": "حسب المزوّد",
        "privacy": "حسب مكان الخادم: داخل مؤسستك أو لدى المزوّد",
        "internet": "حسب مكان الخادم",
        "quality": "حسب النموذج",
        "key_url": "", "pricing_url": "", "docs_url": "",
    },
    "ollama": {
        "title": "Ollama (برنامج منفصل)",
        "what": "لمن ثبّت برنامج Ollama على جهازه: يستعمل نماذجه المنزَّلة فيه. البديل الأسهل هو «محلي مدمج» دون تثبيت شيء.",
        "needs": ["تثبيت Ollama من ollama.com وتنزيل نموذج فيه"],
        "cost": "مجاني",
        "privacy": "النص لا يغادر جهازك",
        "internet": "عند تنزيل النموذج فقط",
        "quality": "حسب النموذج",
        "key_url": "", "pricing_url": "", "docs_url": "https://ollama.com",
    },
}
