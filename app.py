# -*- coding: utf-8 -*-
import streamlit as st
import pandas as pd
import requests
import json
from collections import Counter
from fpdf import FPDF
import datetime
import io
import os

# --- URL DE LA BASE FFE (REMPLACEZ PAR VOTRE LIEN EXCEL PUBLIC !) ---
# Cette URL doit pointer vers un fichier .xls ou .xlsx contenant les feuilles "joueur" et "club".
FFE_DATA_URL = "http://basilevinet.com/data/BaseFFE.xls" 

# --- CONFIGURATION ---
st.set_page_config(page_title="♟️ MasterCoach", layout="wide", page_icon="♟️")

# --- PERSISTENCE (Sauvegarde des Liaisons) ---
MAPPINGS_FILE = "mappings.json"

@st.cache_data
def load_mappings():
    # Tente de charger les mappings existants
    try:
        with open(MAPPINGS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def save_mappings(mappings_dict):
    # Sauvegarde les mappings dans le fichier JSON
    try:
        with open(MAPPINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(mappings_dict, f, indent=4)
    except Exception as e:
        st.error(f"Erreur lors de la sauvegarde des liaisons : {e}")
        
# --- FONCTION DE CHARGEMENT PERMANENT PAR URL (Lecture XLSX/XLS) ---
@st.cache_data
def load_permanent_ffe_data(url):
    try:
        # Tente de lire les deux feuilles du fichier Excel hébergé
        all_sheets = pd.read_excel(url, sheet_name=None)
        
        # S'assurer que les feuilles existent après conversion
        df_joueurs = all_sheets.get("joueur")
        df_clubs = all_sheets.get("club")     
        
        if df_joueurs is None or df_clubs is None:
             st.error("Erreur: Impossible de trouver les feuilles nommées 'joueur' et 'club' dans le fichier Excel.")
             return pd.DataFrame()
        
        # 1. Préparation et jointure des données
        
        # Nettoyage et combinaison des noms de joueurs (Nom Prenom)
        df_joueurs['Nom Joueur'] = df_joueurs['Nom'].str.upper() + ' ' + df_joueurs['Prenom'].str.title()
        
        # Renommage des colonnes des clubs pour la jointure
        df_clubs = df_clubs.rename(columns={'Ref': 'ClubRef', 'Nom': 'Nom Club'})
        
        # Sélection des colonnes essentielles pour la jointure
        df_clubs = df_clubs[['ClubRef', 'Nom Club']]
        
        # Jointure des joueurs et des noms de clubs
        df_final = pd.merge(df_joueurs, df_clubs, on='ClubRef', how='left')
        
        # Conversion du ClubRef en entier
        df_final['ClubRef'] = pd.to_numeric(df_final['ClubRef'], errors='coerce').astype('Int64')
        
        # Sélection des colonnes finales pour l'application
        df_final = df_final[['Nom Joueur', 'Cat', 'Elo', 'ClubRef', 'Nom Club']].copy()

        # Renommage pour correspondre au reste de l'application
        df_final = df_final.rename(columns={'Nom Joueur': 'Nom'}) 
        
        st.sidebar.success(f"{len(df_final)} joueurs chargés et joints avec les clubs.")
        return df_final
        
    except Exception as e:
        st.error(f"Erreur de chargement de la base FFE. Vérifiez que l'URL est correcte et que le fichier est public. Détail: {e}")
        return pd.DataFrame()

# --- CLASS PDF / get_player_stats (Identique) ---
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
    st.session_state['mappings'] = load_mappings() 

st.title("♟️ MasterCoach - Manager")

# CHARGEMENT PERMANENT DE LA BASE FFE
df = load_permanent_ffe_data(FFE_DATA_URL)

# Fichier: app.py (dans la section MAIN APP)

# ... (le code avant with st.sidebar:) ...

with st.sidebar:
    st.subheader("Configuration du Club")
    
    if not df.empty:
        # Créer un DataFrame des clubs uniques (Nom Club et ClubRef)
        df_clubs_map = df[['ClubRef', 'Nom Club']].drop_duplicates().dropna(subset=['Nom Club'])
        
        # Créer un dictionnaire Nom -> ID
        club_name_to_id = pd.Series(df_clubs_map['ClubRef'].values, 
                                    index=df_clubs_map['Nom Club']).to_dict()
        
        # Créer la liste des noms pour le SelectBox (triée)
        club_names = sorted(club_name_to_id.keys())
        
        # Tenter de sélectionner le club de l'utilisateur s'il existe (ex: 'AS P' pour les tests)
        default_index = 0
        try:
             # Si vous voulez cibler votre club par défaut, changez cette logique
             user_club_name = df_clubs_map.loc[df_clubs_map['ClubRef'] == 999, 'Nom Club'].iloc[0]
             default_index = club_names.index(user_club_name)
        except:
             pass

        # 1. Utiliser le Nom du Club dans le SelectBox
        selected_club_name = st.selectbox(
            "Nom du Club à filtrer", 
            club_names, 
            index=default_index
        )
        
        # 2. Récupérer l'ID correspondant au nom sélectionné
        club_id = club_name_to_id.get(selected_club_name)

        # Affichage de confirmation (optionnel, pour le debug)
        st.caption(f"ID Club sélectionné : {club_id}")
        
    else:
        st.error("Base FFE non chargée.")
        club_id = 0


# Le reste du code utilise maintenant 'club_id' pour filtrer la base:
if not df.empty and club_id:
    # FILTRAGE FINAL PAR L'ID RÉCUPÉRÉ
    club_players = df[df['ClubRef'] == club_id]
    
# ... (le reste du code) ...


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
                    save_mappings(st.session_state['mappings'])
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
        st.error(f"Aucun joueur trouvé pour l'ID Club {club_id}. Vérifiez l'ID sélectionné.")

# Message d'erreur si la base n'a pas pu être chargée du tout
elif FFE_DATA_URL == "VOTRE_URL_EXPORT_EXCEL":
     st.warning("⚠️ Veuillez remplacer VOTRE_URL_EXPORT_EXCEL par l'URL de votre fichier FFE hébergé.")



