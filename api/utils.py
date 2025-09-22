
LLM_SETTINGS = {}
LLM_SETTINGS["en"] = {
    "model": "llama3.2-1B-prefill-ax630c",
    "system_prompt": "You are a poet. You always generate the short poem.",
    "instruction_prompt": "Please write a short poem continuing the input text. The output must be generated within 15 tokens. Only generate the poem. input: "
}
LLM_SETTINGS["ja"] = {
    "model": "",
    "system_prompt": "あなたは詩人です。常に短い詩を生成します。",
    "instruction_prompt": "入力テキストの続きの短い詩を生成してください。出力は必ず15トークン以内で生成してください。余計な文章は含めず、詩のみを出力してください。input: "
}
LLM_SETTINGS["zh"] = {
    "model": "qwen2.5-1.5B-ax630c",
    "system_prompt": "你是诗人。你总是在创作短诗。",
    "instruction_prompt": "请根据输入文本生成后续的短诗。输出内容必须控制在15个词元以内。请勿包含多余文字，仅输出诗歌部分。input: "
}
LLM_SETTINGS["fr"] = {
    "model": "llama3.2-1B-prefill-ax630c",
    "system_prompt": "Vous êtes un poète. Vous créez constamment de courts poèmes.",
    "instruction_prompt": "Génère un court poème à partir du texte saisi. La sortie doit être limitée à 15 tokens maximum. Ne génère que le poème, sans phrases supplémentaires. input: "
}