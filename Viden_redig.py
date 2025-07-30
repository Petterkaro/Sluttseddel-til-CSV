import streamlit as st
import pdfplumber
import pandas as pd
import re
import io
from datetime import datetime

st.title("PDF til CSV \U0001F4C4 ➡️ strukturert utlesing av handelsdata")

uploaded_files = st.file_uploader(
    "Last opp en eller flere handelsbekreftelser (PDF)",
    type="pdf",
    accept_multiple_files=True
)

# --- Hjelpefunksjoner ---

def finn_desimaltegn_fra_beløp(verdi):
    verdi = verdi.strip().replace("\u202f", "").replace(" ", "")
    match = re.match(r"^.*([.,])(\d{2})$", verdi)
    if match:
        return match.group(1)
    return "."

def normaliser_tall(tall, desimaltegn="."):
    if not tall:
        return ""
    tall = tall.strip().replace("\u202f", "").replace(" ", "")
    tusenskille = "," if desimaltegn == "." else "."
    tall = tall.replace(tusenskille, "").replace(desimaltegn, ".")
    try:
        return str(float(tall))
    except:
        return tall

def hent_verdi_med_fast_mal(linjer, nøkkelord_liste):
    for nøkkelord in nøkkelord_liste:
        for linje in linjer:
            if nøkkelord.lower() in linje.lower():
                match = re.findall(r"[\d.,]+", linje)
                if match:
                    return match[-1]
    return ""

def hent_beløp_fallback(linjer):
    kandidater = []
    for linje in linjer:
        match = re.findall(r"[\d.,]+\d{2}", linje)
        for m in match:
            if re.match(r"^\d{1,3}([.,]?\d{3})*([.,]\d{2})$", m.strip()):
                kandidater.append(m.strip())
    if kandidater:
        def try_parse(val):
            try:
                punktum = finn_desimaltegn_fra_beløp(val)
                return float(normaliser_tall(val, punktum))
            except:
                return 0.0
        største = max(kandidater, key=try_parse)
        return største
    return ""

def hent_antall_med_fallback(linjer):
    for nøkkelord in ["Antall kjøpt", "Antall solgt", "Antall"]:
        for linje in linjer:
            if nøkkelord.lower() in linje.lower():
                match = re.findall(r"[\d.,]+", linje)
                if match:
                    return match[-1]
    for linje in linjer:
        if re.search(r"\d{2}[./]\d{2}[./]\d{4}", linje):
            continue
        match = re.findall(r"\b\d{1,3}(?:[.,\s]?\d{3})*(?:[.,]\d{2})?\b", linje)
        if match:
            return match[0]
    return ""

def finn_valuta(linjer):
    for linje in linjer:
        if "eur" in linje.lower(): return "EUR"
        elif "nok" in linje.lower(): return "NOK"
        elif "usd" in linje.lower(): return "USD"
        elif "sek" in linje.lower(): return "SEK"
        elif "dkk" in linje.lower(): return "DKK"
    return ""

def finn_bankforkortelse(tekst):
    bank_mapping = {
        "fearnley securities": "FEAR",
        "fearnley": "FEAR",
        "sparebank 1": "SB1M",
        "carnegie": "DNB",
        "dnb": "DNB",
        "alfred berg": "AB",
        "abg": "ABG",
        "arctic": "ARC",
        "klp": "KLP",
        "norne": "NORNE",
        "pareto": "PAR"
    }
    tekst = tekst.lower()
    for navn, forkortelse in bank_mapping.items():
        if navn in tekst:
            return forkortelse
    return ""

def hent_ticker(linjer):
    for linje in linjer:
        if "ticker" in linje.lower():
            deler = linje.strip().split()
            if len(deler) >= 2:
                return deler[-1].strip().upper()
    for i, linje in enumerate(linjer):
        if re.search(r"\b[A-Z]{2}\d{10}\w?\b", linje):
            deler = linje.strip().split()
            for j, deltekst in enumerate(deler):
                if re.match(r"^[A-Z]{2}\d{10}\w?$", deltekst):
                    if j + 1 < len(deler):
                        kandidat = deler[j + 1].strip().upper()
                        if 2 <= len(kandidat) <= 6 and kandidat.isalnum():
                            return kandidat
    return "VIDEN"

def hent_data_handelsbekreftelse(linjer):
    tekst = "\n".join(linjer)
    kjøp_salg = "by" if any("kjøpt" in l.lower() for l in linjer) else "sl" if any("solgt" in l.lower() for l in linjer) else ""
    salgskode = "f" if kjøp_salg == "sl" else ""

    rå_beløp = hent_verdi_med_fast_mal(linjer, ["Oppgjørsbeløp", "Totalt i Deres favør", "Oppgjørsbeløp NOK", "Total"])
    if not rå_beløp:
        rå_beløp = hent_beløp_fallback(linjer)

    desimaltegn = finn_desimaltegn_fra_beløp(rå_beløp)
    beløp = normaliser_tall(rå_beløp, desimaltegn)

    kurs = normaliser_tall(hent_verdi_med_fast_mal(linjer, ["Pris", "Kurs"]), desimaltegn)
    antall = normaliser_tall(hent_antall_med_fallback(linjer), desimaltegn)
    kurtasje = normaliser_tall(hent_verdi_med_fast_mal(linjer, ["Kurtasje"]), desimaltegn)

    if not antall or not kurs:
        for linje in linjer:
            if re.search(r"\bNO\d{10}\b", linje):
                deler = linje.strip().split()
                try:
                    antall = normaliser_tall(deler[-4], desimaltegn)
                    kurs = normaliser_tall(deler[-3], desimaltegn)
                except:
                    pass
                break

    full_tekst = tekst.lower()
    siste_tekstblokker = "\n".join(linjer[-30:]).lower()
    bank = finn_bankforkortelse(full_tekst + "\n" + siste_tekstblokker)

    return {
        "kjøp_salg": kjøp_salg,
        "salgskode": salgskode,
        "kjøpsdato": hent_verdi_med_fast_mal(linjer, ["Handelsdato"]),
        "oppgjørsdato": hent_verdi_med_fast_mal(linjer, ["Oppgjørsdato"]),
        "antall": antall,
        "kurs": kurs,
        "valuta": finn_valuta(linjer),
        "beløp": beløp,
        "kurtasje": kurtasje,
        "bank": bank,
        "ticker": hent_ticker(linjer),
    }

def format_dato(dato_str):
    try:
        if "." in dato_str:
            dt = datetime.strptime(dato_str, "%d.%m.%Y")
        elif len(dato_str) == 8 and "" not in dato_str:
            dt = datetime.strptime(dato_str, "%d%m%Y")
        else:
            return dato_str
        return dt.strftime("%m%d%Y")
    except:
        return dato_str

def bygg_csv_rad(verdi_dict):
    kjøpsdato = format_dato(verdi_dict.get("kjøpsdato", ""))
    oppgjørsdato = format_dato(verdi_dict.get("oppgjørsdato", ""))
    salgskode = verdi_dict.get("salgskode", "")

    return [
        "Petter", verdi_dict.get("kjøp_salg", ""), "", "csno", verdi_dict.get("ticker", "VIDEN"), kjøpsdato,
        oppgjørsdato, "", verdi_dict.get("antall", ""), salgskode, "", "cano",
        "$cash", "", "", "", "y", verdi_dict.get("beløp", ""), "", "", "", "5", "",
        verdi_dict.get("kurtasje", ""), "", "n", "", "", "n", "1", *[""] * 11, "1", "", "",
        "n", "y", *[""] * 31, verdi_dict.get("bank", ""), *[""] * 25
    ]

# --- Hovedprogram ---

if uploaded_files:
    alle_rader = []

    for uploaded_file in uploaded_files:
        with pdfplumber.open(uploaded_file) as pdf:
            linjer = []
            for side in pdf.pages:
                linjer += side.extract_text().split('\n')

            verdi_dict = hent_data_handelsbekreftelse(linjer)

            st.subheader(f"\U0001F9FE {uploaded_file.name}")

            # Redigerbart skjema med unike keys per PDF
            med_endringer = {}
            col1, col2 = st.columns(2)

            with col1:
                med_endringer["kjøp_salg"] = st.selectbox("Kjøp/salg", ["by", "sl"],
                    index=["by", "sl"].index(verdi_dict["kjøp_salg"]),
                    key=f"kjøp_salg_{uploaded_file.name}")
                med_endringer["salgskode"] = st.text_input("Salgskode", verdi_dict["salgskode"], key=f"salgskode_{uploaded_file.name}")
                med_endringer["kjøpsdato"] = st.text_input("Kjøpsdato", verdi_dict["kjøpsdato"], key=f"kjøpsdato_{uploaded_file.name}")
                med_endringer["oppgjørsdato"] = st.text_input("Oppgjørsdato", verdi_dict["oppgjørsdato"], key=f"oppgjørsdato_{uploaded_file.name}")
                med_endringer["bank"] = st.text_input("Bank", verdi_dict["bank"], key=f"bank_{uploaded_file.name}")
                med_endringer["ticker"] = st.text_input("Ticker", verdi_dict["ticker"], key=f"ticker_{uploaded_file.name}")

            with col2:
                med_endringer["antall"] = st.text_input("Antall", verdi_dict["antall"], key=f"antall_{uploaded_file.name}")
                med_endringer["kurs"] = st.text_input("Kurs", verdi_dict["kurs"], key=f"kurs_{uploaded_file.name}")
                med_endringer["valuta"] = st.text_input("Valuta", verdi_dict["valuta"], key=f"valuta_{uploaded_file.name}")
                med_endringer["beløp"] = st.text_input("Beløp", verdi_dict["beløp"], key=f"beløp_{uploaded_file.name}")
                med_endringer["kurtasje"] = st.text_input("Kurtasje", verdi_dict["kurtasje"], key=f"kurtasje_{uploaded_file.name}")

            rad = bygg_csv_rad(med_endringer)
            alle_rader.append(rad)

    df = pd.DataFrame(alle_rader)
    output = io.StringIO()
    df.to_csv(output, header=False, index=False)
    csv_data = output.getvalue()
    output.close()

    st.download_button(
        label="\U0001F4E5 Last ned samlet CSV",
        data=csv_data.encode("utf-8"),
        file_name="handelsdata_samlet.csv",
        mime="text/csv"
    )
