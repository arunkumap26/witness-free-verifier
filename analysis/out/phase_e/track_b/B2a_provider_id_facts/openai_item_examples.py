"""Decode OpenAI Responses-API ids printed in official openai-cookbook notebook outputs (time-first hex layout hypothesis:
unix seconds = int(hex[0:8], 16)); compare with the created_at printed for the same Response object."""
import datetime as dt, json
EX = [  # (id, created_at printed with the same object or None, source notebook)
 ("resp_67bd65392a088191a3b802a61f4fba14", 1740465465, "examples/responses_api/responses_example.ipynb"),
 ("msg_67bd6502568c8191a2cbb154fa3fbf4c", None, "examples/responses_api/responses_example.ipynb"),
 ("msg_67bd653ab9cc81918db973f0c1af9fbb", None, "examples/responses_api/responses_example.ipynb"),
 ("msg_67bd653f34fc8191989241b2659fd1b5", None, "examples/responses_api/responses_example.ipynb"),
 ("ws_67bd64fe91f081919bec069ad65797f1", None, "examples/responses_api/responses_example.ipynb"),
 ("ws_67bd653c7a548191af86757fbbca96e1", None, "examples/responses_api/responses_example.ipynb"),
 ("resp_6820f382ee1c8191bc096bee70894d040ac5ba57aafcbac7", 1746989954, "examples/responses_api/reasoning_items.ipynb"),
 ("rs_6820f383d7c08191846711c5df8233bc0ac5ba57aafcbac7", None, "examples/responses_api/reasoning_items.ipynb"),
 ("msg_6820f3854688819187769ff582b170a60ac5ba57aafcbac7", None, "examples/responses_api/reasoning_items.ipynb"),
 ("rs_68210c71a95c81919cc44afadb9d220400c77cc15fd2f785", None, "examples/responses_api/reasoning_items.ipynb"),
 ("fc_68210c78357c8191977197499d5de6ca00c77cc15fd2f785", None, "examples/responses_api/reasoning_items.ipynb"),
 ("rs_6821243503d481919e1b385c2a154d5103d2cbc5a14f3696", None, "examples/responses_api/reasoning_items.ipynb"),
 ("rs_6894e31b1f8081999d18325e5ceffcfe0861a2e1728d1664", None, "examples/gpt-5/gpt-5_new_params_and_tools.ipynb"),
 ("ctc_6894e31c66f08199abd622bb5ac3c4260861a2e1728d1664", None, "examples/gpt-5/gpt-5_new_params_and_tools.ipynb"),
]
for s, ca, src in EX:
    pre, h = s.split("_", 1)
    t = int(h[:8], 16)
    print(json.dumps({"id": s, "prefix": pre, "hex_len": len(h), "hex0_8_sec": t,
                      "iso": dt.datetime.fromtimestamp(t, dt.timezone.utc).isoformat(), "hex12_16": h[12:16],
                      "tail16": h[-16:] if len(h) == 48 else None, "created_at_printed": ca,
                      "match_created_at": (t == ca) if ca else None, "source": src}))
