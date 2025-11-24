# -*- coding: utf-8 -*-
import streamlit as st
import pandas as pd
import requests
import json
from collections import Counter
from fpdf import FPDF
import datetime
import io
import os # NOUVEAU: Pour la gestion du fichier

# --- CONFIGURATION ---
st.set_page_config(page_title="MasterCoach Echecs", layout="wide", page_icon="♟️")

# --- PERSISTENCE (Sauvegarde des Liaisons) ---
MAPPINGS_FILE = "mappings.json"

def load_mappings():
    # Tente de charger les mappings existants
    try:
        with open(MAPPINGS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        # Retourne un dictionnaire vide si le fichier n'existe pas ou est corrompu
        return {}

def save_mappings(mappings_dict):
    # Sauvegarde les mappings dans le fichier JSON
    try:
        with open(MAPPINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(mappings_dict, f, indent=4)
    except Exception as e:
        st.error(f"Erreur lors de la sauvegarde des liaisons : {e}")


# --- CLASS PDF ---
class PDFReport(FPDF):
    def header(self):
        self.set_font('Arial', 'B', 16)
        self.cell(0, 10, 'FICHE DE PREPARATION - MATCH', 0, 1, 'C')
        self.ln(5)
    def footer(self):
        self.set_y(-15)
        self.set_font('Arial', 'I', 8)
        self.cell(0, 10, f'Genere le {datetime.date.today()} par MasterCoach App', 0, 0, 'C')

def create_pdf_download(target_name, pseudo, df_white, df_black):
    pdf = PDFReport()
    pdf.add_page()
    pdf.set_font("Arial", size=12)
    pdf.cell(0, 10, f"Adversaire : {target_name}", ln=True)
    pdf.cell(0, 10, f"Pseudo Lichess : {pseudo}", ln=True)
    pdf.line(10, 45, 200, 45)
    pdf.ln(10)
    
    pdf.set_font("Arial", 'B', 14)
    pdf.cell(0, 10, "AVEC LES BLANCS (Il joue...)", ln=True)
    pdf.set_font("Arial", size=11)
    if df_white is not None and not df_white.empty:
        for index, row in df_white.iterrows():
            ouverture = str(row['Ouverture']).encode('latin-1', 'replace').decode('latin-1')
            pdf.cell(0, 8, f"- {ouverture} ({row['Fréquence']}x)", ln=True)
    else:
        pdf.cell(0, 8, "Pas assez de donnees.", ln=True)
    pdf.ln(5)
    
    pdf.set_font("Arial", 'B', 14)
    pdf.cell(0, 10, "AVEC LES NOIRS (Il defend...)", ln=True)
    pdf.set_font("Arial", size=11)
    if df_black is not None and not df_black.empty:
        for index, row in df_black.iterrows():
            ouverture = str(row['Ouverture']).encode('latin-1', 'replace').decode('latin-1')
            pdf.cell(0, 8, f"- {ouverture} ({row['Fréquence']}x)", ln=True)
    else:
        pdf.cell(0, 8, "Pas assez de donnees.", ln=True)
    pdf.ln(10)
    
    pdf.set_font("Arial", 'B', 12)
    pdf.cell(0, 10, "NOTES DU COACH :", ln=True)
    pdf.set_fill_color(240, 240, 240)
    pdf.rect(x=10, y=pdf.get_y(), w=190, h=60, style='F')
    
    return pdf.output(dest='S').encode('latin-1')

def get_player_stats(username, nb_games=50):
    url = f"https://lichess.org/api/games/user/{username}?max={nb_games}&opening=true"
    headers = {"Accept": "application/x-ndjson"}
    try:
        response = requests.get(url, headers=headers)
        games = [json.loads(line) for line in response.text.strip().split('\n') if line]
        if not games: return None, None

        w_ops, b_ops = [], []
        for game in games:
            opening = game.get('opening', {}).get('name', 'Inconnue')
            try:
                if game['players']['white']['user']['name'].lower() == username.lower():
                    w_ops.append(opening)
                else:
                    b_ops.append(opening)
            except: continue
            
        df_w = pd.DataFrame(Counter(w_ops).most_common(5), columns=['Ouverture', 'Fréquence'])
        df_b = pd.DataFrame(Counter(b_ops).most_common(5), columns=['Ouverture', 'Fréquence'])
        return df_w, df_b
    except: return None, None

# --- MAIN APP ---
if 'mappings' not in st.session_state:
    # Charge les données persistantes au démarrage
    st.session_state['mappings'] = load_mappings() 

st.title("♟️ MasterCoach - Manager")

df = pd.DataFrame()
uploaded_file = None

with st.sidebar:
    st.subheader("Chargement des Données FFE")
    uploaded_file = st.file_uploader("Importer le fichier joueurs FFE (CSV ou TXT)", type=["csv", "txt"])
    
    club_id = st.number_input("ID Club à filtrer", value=999)
    st.info("Utilisez l'ID pour filtrer votre club. Ex: 999")

if uploaded_file is not None:
    try:
        # Lecture du fichier FFE (souvent séparé par des points-virgules et encodé en latin-1)
        df = pd.read_csv(uploaded_file, sep=';', encoding='latin-1', on_bad_lines='skip')
        st.sidebar.success(f"{len(df)} joueurs chargés. Colonnes: {', '.join(df.columns)}")
        
        # S'assurer que les colonnes nécessaires existent
        required_cols = ['Nom', 'Cat', 'Elo', 'ClubRef']
        if not all(col in df.columns for col in required_cols):
             st.error("Erreur: Le fichier FFE doit contenir les colonnes Nom, Cat, Elo et ClubRef.")
             df = pd.DataFrame()
        
    except Exception as e:
        st.error(f"Erreur de lecture du fichier : {e}. Vérifiez le format (séparateur ';', encodage 'latin-1').")
else:
    st.warning("Veuillez charger votre fichier FFE (TXT/CSV) dans la barre latérale.")


# Si le fichier a été chargé et lu correctement:
if not df.empty:
    club_players = df[df['ClubRef'] == club_id]
    
    if not club_players.empty:
        t1, t2, t3 = st.tabs(["📋 Équipe", "🔗 Liaison Lichess", "⚔️ Prépa Match"])
        
        with t1:
            st.dataframe(club_players)
            st.subheader("Suggestion Top Jeunes")
            cols = st.columns(4)
            for i, cat in enumerate(["Minime", "Benjamin", "Pupille", "Poussin"]):
                with cols[i]:
                    st.markdown(f"**{cat}**")
                    best = club_players[club_players['Cat'] == cat].nlargest(1, 'Elo')
                    if not best.empty: st.success(f"{best.iloc[0]['Nom']} ({best.iloc[0]['Elo']})")
        
        with t2:
            player_options = club_players['Nom'].unique() if 'Nom' in club_players.columns else []
            p = st.selectbox("Joueur", player_options)
            
            if p:
                curr = st.session_state['mappings'].get(p, "")
                new = st.text_input("Pseudo Lichess", value=curr)
                if st.button("Lier"):
                    st.session_state['mappings'][p] = new
                    save_mappings(st.session_state['mappings']) # NOUVEAU: Sauvegarde persistante
                    st.success(f"Liaison sauvegardée et enregistrée pour {p}: {new}")
            
        with t3:
            targets = [p for p in club_players['Nom'] if p in st.session_state['mappings']]
            if targets:
                tgt = st.selectbox("Cible", targets)
                pseudo = st.session_state['mappings'][tgt]
                if st.button("Analyser"):
                    df_w, df_b = get_player_stats(pseudo)
                    if df_w is not None:
                        c1, c2 = st.columns(2)
                        with c1: 
                            st.write("Blancs"); st.dataframe(df_w, hide_index=True)
                        with c2: 
                            st.write("Noirs"); st.dataframe(df_b, hide_index=True)
                        
                        pdf = create_pdf_download(tgt, pseudo, df_w, df_b)
                        st.download_button("📄 Télécharger PDF", pdf, "prepa.pdf", "application/pdf")
            else:
                st.warning("Liez d'abord un pseudo dans l'onglet 2.")
    else:
        st.error(f"Aucun joueur trouvé pour l'ID Club {club_id}. Vérifiez l'ID et les données chargées.")
