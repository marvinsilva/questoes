#!/usr/bin/env python3
"""Converte os PDFs de pdfs/ em JSON em questoes/.  Uso: python tools/pdf_para_json.py
Requer: pip install pymupdf"""
import json, re, unicodedata
from pathlib import Path
import fitz  # pymupdf

RAIZ = Path(__file__).resolve().parent.parent
# Caracteres que alguns PDFs trocam no lugar de ligaduras/espaços
TROCAS = {"Ɵ": "ti", "ơ": "tí", "İ": "fí", "Ō": "ft", "Ê": " ", "\u00a0": " "}
ASSUNTOS = {
    "Disfagia": r"degluti|disfagi|faring|esofag|aspira",
    "Voz": r"\bvoz\b|vocal|disfonia|prega|laring",
    "Aleitamento e fissuras": r"leite|amament|colostro|fissura|sucção",
    "Linguagem escrita": r"alfab|ortogr|leitura|escrita|consciência fonol|grafema",
    "Fonologia": r"fonem|alofone|onset|\bcoda\b|fonológ|glide|epêntese|metátese",
    "Saúde coletiva": r"\bSUS\b|\bRAS\b|CAPS|RENAST|\bPSE\b|eMulti|Constituição|vigilância|Rede de",
    "Audiologia": r"auditiv|audiom|audiológic|limiar|otoac|imit[aâ]nc|orelha|coclear|AASI|PEATE|mascaramento|ruído",
}
RE_Q = re.compile(r"^QUEST[ÃA]O\s*(\d+)\s*[–-]\s*(.*)")
RE_ALT = re.compile(r"^\(?([A-E])\)\s*(.*)")
RE_GAB = re.compile(r"^(?:\d{1,4}\s*-\s*[A-E]\s*)+$")
RE_CAPS = re.compile(r"^[A-ZÀ-Ú ]{8,}$")
RE_QUEBRA = re.compile(r"^(?:[IVX]+\.|\(\s*\)|Coluna|\d\.)")


def slugify(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def limpar(txt):
    for a, b in TROCAS.items():
        txt = txt.replace(a, b)
    out = []
    for l in txt.splitlines():
        l = re.sub(r"\s+", " ", l).strip()
        if not l or re.fullmatch(r"\d{1,3}", l) or l.startswith(("Licenciado para", "Compilado")):
            continue
        out.append(l)
    return out


def classificar(texto):
    pontos = {a: len(re.findall(p, texto, re.I)) for a, p in ASSUNTOS.items()}
    melhor = max(pontos, key=pontos.get)
    return melhor if pontos[melhor] else "Geral"


def parse(linhas, fonte, slug):
    qs, gab, ctxs, atual, ctx = [], {}, [], None, None
    for l in linhas:
        if RE_GAB.match(l):
            gab.update({int(n): a for n, a in re.findall(r"(\d{1,4})\s*-\s*([A-E])", l)})
            continue
        if "GABARITO" in l or RE_CAPS.match(l):
            continue
        m = RE_Q.match(l)
        if m:
            if ctx is not None:
                t = " ".join(ctx)
                r = re.search(r"quest[õo]es\s+(?:de\s+)?(\d+)\s*(?:a|e)\s*(\d+)", t)
                if r:
                    ctxs.append((int(r[1]), int(r[2]), t[r.end():].lstrip(", ")))
                ctx = None
            atual = {"n": int(m[1]), "enun": [m[2]], "alts": {}}
            qs.append(atual)
            continue
        if l.startswith("Para responder"):
            ctx = [l]
            continue
        if ctx is not None:
            ctx.append(l)
            continue
        if atual is None:
            continue
        a = RE_ALT.match(l)
        if a and len(atual["alts"]) < 5 and a[1] == "ABCDE"[len(atual["alts"])]:
            atual["alts"][a[1]] = a[2]
        elif atual["alts"]:
            atual["alts"][list(atual["alts"])[-1]] += " " + l
        else:
            atual["enun"].append(("\n" if RE_QUEBRA.match(l) else " ") + l)
    nums = {q["n"] for q in qs}
    for i in range(len(qs) - 1):  # numeração duplicada no PDF
        if qs[i]["n"] == qs[i + 1]["n"] and qs[i]["n"] - 1 not in nums:
            qs[i]["n"] -= 1
            qs[i]["ajustada"] = True
    saida = []
    for q in qs:
        n, enun = q["n"], "".join(q["enun"]).strip()
        ctx_txt = next((t for a, b, t in ctxs if a <= n <= b), "")
        g = gab.get(n, "")
        saida.append({
            "id": f"{slug}-{n}", "numero": n, "assunto": classificar(enun + " " + " ".join(q["alts"].values())),
            "contexto": ctx_txt, "enunciado": enun, "alternativas": q["alts"], "gabarito": g, "comentarios": {},
            "revisar": q.get("ajustada", False) or len(q["alts"]) < 2 or g not in q["alts"],
        })
    return saida


def main():
    (RAIZ / "questoes").mkdir(exist_ok=True)
    indice = []
    for pdf in sorted((RAIZ / "pdfs").glob("*.pdf")):
        slug = slugify(pdf.stem)
        destino = RAIZ / "questoes" / f"{slug}.json"
        antigos = {}
        if destino.exists():  # preserva comentários já escritos
            antigos = {q["id"]: q for q in json.loads(destino.read_text("utf-8"))["questoes"]}
        with fitz.open(pdf) as doc:
            texto = "\n".join(p.get_text() for p in doc)
        qs = parse(limpar(texto), pdf.stem, slug)
        for q in qs:
            if q["id"] in antigos:
                q["comentarios"] = antigos[q["id"]].get("comentarios", {})
        destino.write_text(json.dumps({"fonte": pdf.stem, "questoes": qs}, ensure_ascii=False, indent=1), "utf-8")
        indice.append({"arquivo": destino.name, "fonte": pdf.stem, "total": len(qs)})
        print(f"{pdf.name}: {len(qs)} questões, {sum(q['revisar'] for q in qs)} para revisar")
    (RAIZ / "questoes" / "index.json").write_text(json.dumps(indice, ensure_ascii=False, indent=1), "utf-8")


if __name__ == "__main__":
    main()
