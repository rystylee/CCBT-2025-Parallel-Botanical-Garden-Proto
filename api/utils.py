LLM_SETTINGS = {}
LLM_SETTINGS["en"] = {
    # "model": "llama3.2-1B-prefill-ax630c",
    "model": "qwen2.5-0.5B-prefill-20e",
    "system_prompt": "You are a poet. You always generate short poems in English.",
    "translation_prompt": "Please translate the input text into English. Output only the translated results. input: ",
    "instruction_prompt": "Please generate a short poem in English based on the input text. The output must be generated within 15 tokens. Only generate the poem. input: "
}
LLM_SETTINGS["ja"] = {
    # "model": "TinySwallow-1.5B",
    "model": "qwen2.5-0.5B-prefill-20e",
    "system_prompt": "あなたは詩人です。常に短い詩を日本語で生成します。",
    "translation_prompt": "入力テキストを日本語に翻訳してください。翻訳した結果のみを出力してください。input: ",
    "instruction_prompt": "入力テキストの続きの短い詩を日本語で生成してください。出力は必ず15トークン以内で生成してください。余計な文章は含めず、詩のみを出力してください。input: "
}
LLM_SETTINGS["zh"] = {
    # "model": "qwen2.5-1.5B-ax630c",
    "model": "qwen2.5-0.5B-prefill-20e",
    "system_prompt": "你是诗人。你总是在用中文生成短诗。",
    "translation_prompt": "请将输入文本翻译成中文。请仅输出翻译结果。input: ",
    "instruction_prompt": "请用中文生成输入文本后续的短诗。输出内容必须控制在15个词元以内。请勿包含多余文字，仅输出诗歌部分。input: "
}
LLM_SETTINGS["fr"] = {
    # "model": "llama3.2-1B-prefill-ax630c",
    "model": "qwen2.5-0.5B-prefill-20e",
    "system_prompt": "Vous êtes un poète. Vous êtes un poète. Vous générez toujours de courts poèmes en français.",
    "translation_prompt": "Traduisez le texte saisi en français. Veuillez afficher uniquement le résultat de la traduction. input: ",
    "instruction_prompt": "Veuillez générer un court poème en français à partir du texte saisi. La sortie doit être limitée à 15 tokens maximum. Ne génère que le poème, sans phrases supplémentaires. input: "
}

TTS_SETTINGS = {}
TTS_SETTINGS["en"] = {
    "model": "melotts-en-us"
}
TTS_SETTINGS["ja"] = {
    "model": "melotts-ja-jp"
}
TTS_SETTINGS["zh"] = {
    "model": "melotts-zh-cn"
}
TTS_SETTINGS["fr"] = {
    "model": "melotts-en-us"
}