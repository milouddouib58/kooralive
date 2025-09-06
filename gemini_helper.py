# -*- coding: utf-8 -*-
import os
import json
import google.generativeai as genai


def _configure_gemini(api_key: str = None):
    """
    تهيئة مكتبة Gemini باستخدام مفتاح API.
    - إذا لم يتم تمرير api_key يتم البحث عنه في متغير البيئة GEMINI_API_KEY.
    """
    key = api_key or os.getenv("GEMINI_API_KEY")
    if not key:
        raise RuntimeError(
            "GEMINI_API_KEY غير مضبوط. "
            "ضعه في Secrets أو أدخله في الحقل داخل التطبيق."
        )
    genai.configure(api_key=key)


def analyze_with_gemini(
    payload: dict,
    api_key: str = None,
    model_name: str = "gemini-1.5-flash",
    temperature: float = 0.4,
    max_output_tokens: int = 1400,
    language: str = "ar",
    style: str = "مختصر وقابل للتنفيذ",
) -> str:
    """
    تحليل بيانات المراهنات باستخدام نموذج Gemini.
    
    Args:
        payload (dict): البيانات المراد تحليلها.
        api_key (str, optional): مفتاح Gemini API.
        model_name (str): اسم النموذج المستخدم.
        temperature (float): تحكم في تنوع الإجابة.
        max_output_tokens (int): الحد الأقصى لعدد الرموز الناتجة.
        language (str): لغة التحليل.
        style (str): أسلوب الكتابة.

    Returns:
        str: النص التحليلي الناتج من Gemini.
    """
    # تهيئة Gemini
    _configure_gemini(api_key)

    # تحميل النموذج
    model = genai.GenerativeModel(model_name)

    # تحويل البيانات إلى JSON مرتب
    json_blob = json.dumps(payload, ensure_ascii=False, indent=2)

    # بناء البرومبت
    prompt = f"""
    أنت محلّل مراهنات محترف. 
    قدّم تحليل شامل باللغة {language} وبأسلوب {style} اعتماداً على بيانات JSON التالية.

    المطلوب:
    - تقييم احتمالات 1×2 العادلة مقابل أسعار السوق المجُمّعة.
    - إبراز فرص القيمة (Value) حيث p_fair > 1/odds بفارق مجدٍ، مع السبب.
    - مراجعة اقتراحات كيللي (الحجم، المخاطر) وتنبيهات لإدارة المخاطر.
    - تلخيص Over/Under لخط شائع (إن وُجد) وما إذا كان السوق منحازاً.
    - 3–6 توصيات قابلة للتنفيذ + تذكير بأن هذا ليس نصيحة مالية.
    
    رجاءً لا تُرجع JSON في النتيجة — استخدم نصاً منسقاً بعناوين وإيموجي فقط.

    البيانات:
    ```json
    {json_blob}
    ```
    """

    # استدعاء النموذج
    response = model.generate_content(
        prompt,
        generation_config={
            "temperature": temperature,
            "max_output_tokens": max_output_tokens,
        },
    )

    return response.text
