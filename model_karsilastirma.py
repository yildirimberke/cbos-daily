"""CBOS için ücretsiz model deneyi. Yalnızca sentetik, sabit kaynak kartları kullanır."""
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.error import HTTPError
from urllib.request import Request, urlopen

TRIALS = [
    ("openrouter/free", None),
    ("particle-ai/particle-1:free", "high"),
    ("particle-ai/particle-1:free", "max"),
    ("nvidia/nemotron-3-ultra-550b-a55b:free", "high"),
    ("google/gemma-4-31b-it:free", None),
    ("inclusionai/ling-3.2-flash:free", None),
]
CASE = """Kurgusal vaka. Kesim 08.30 TSİ. Bugünkü finansman anketini konu alan tek küpür yaz.
A | 07.55, resmi anket tablosu: Firmaların 12 ay sonrası enflasyon beklentisi
önceki ay %31,80, bu ay %30,50. Piyasa katılımcıları önceki ay %23,89, bu ay %24,04.
B | 08.04, haber ajansı: A'yı aktarıyor. Piyasanın yıl sonu beklentisi %30,00.
C | 08.12, aynı ajansın başka dilde kopyası: ABD Presidente Donald Trump haberleri gölgede kaldı.
D | 09.45, resmi düzeltme: Bu ayki firma beklentisi %29,50.
E | 08.15, köşe yazısı: Anket, ticari kredilerin bugün ucuzladığını kanıtladı.
İstenen alanlar: kaynak (bir kart harfi), eski_fark ve yeni_fark (yüzde puan, JSON sayısı),
baslik (doğal Türkçe), yorum (en fazla iki kısa cümle; iki grubu ve finansmana aktarım sınırını açıkla),
izle (bugün bir bankacının somut olarak kontrol edebileceği bir veri)."""


def request_json(url, key, body=None):
    req = Request(url, headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
                  data=json.dumps(body).encode() if body else None)
    with urlopen(req, timeout=100) as response:
        return json.load(response)


def run_trial(trial, key):
    model, effort = trial
    start = time.monotonic()
    row = {"istenen": model, "ayar": effort or "varsayılan"}
    body = {"model": model, "max_tokens": 6000, "messages": [
        {"role": "system", "content": "Verilen kaynak paketinden çalış. Yalnızca nihai JSON nesnesini döndür."},
        {"role": "user", "content": CASE}]}
    if effort:
        body["reasoning"] = {"effort": effort, "exclude": True}
    try:
        data = request_json("https://openrouter.ai/api/v1/chat/completions", key, body)
        choice = data["choices"][0]
        row.update(model=data.get("model"), bitis=choice.get("finish_reason"),
                   reasoning_token=(data.get("usage", {}).get("completion_tokens_details") or {}).get("reasoning_tokens"))
        raw = choice["message"]["content"].strip()
        note = json.loads(re.sub(r"^`{3}(?:json)?\s*|\s*`{3}$", "", raw, flags=re.I))
        row["kaynak_dogru"] = note.get("kaynak") == "A"
        row["farklar_dogru"] = all(type(note.get(k)) in (int, float) and abs(note[k]-v) < 0.005
                                  for k, v in (("eski_fark", 7.91), ("yeni_fark", 6.46)))
        for k in ("baslik", "yorum", "izle"):
            row[k] = str(note.get(k, ""))[:650]
    except HTTPError as exc:
        row["hata"] = f"HTTP {exc.code}"
    except (ValueError, TypeError, KeyError, IndexError, OSError, AttributeError) as exc:
        row["hata"] = type(exc).__name__
    row["saniye"] = round(time.monotonic()-start, 1)
    return row


def main():
    key = os.environ["OPENROUTER_API_KEY"].strip()
    quota = request_json("https://openrouter.ai/api/v1/key", key)["data"].get("free_model_daily_requests") or {}
    remaining = quota.get("remaining")
    paired = "--paired" in sys.argv
    trials = [TRIALS[1], TRIALS[2], TRIALS[2], TRIALS[1]] if paired else TRIALS
    if type(remaining) is int and remaining < len(trials) + 14:
        raise SystemExit("Günlük bültenler için kota ayrıldı. Deney çalıştırılmadı.")
    if paired:
        for trial in trials:
            row = run_trial(trial, key)
            print("SONUC " + json.dumps(row, ensure_ascii=False), flush=True)
            time.sleep(4)
        return
    with ThreadPoolExecutor(max_workers=2) as pool:
        for row in pool.map(lambda trial: run_trial(trial, key), TRIALS):
            print("SONUC " + json.dumps(row, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
