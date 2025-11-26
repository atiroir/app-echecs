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
from bs4 import BeautifulSoup # Ajout nécessaire pour le scraping SnoopChess

# --- URL DE LA BASE FFE (REMPLACEZ PAR VOTRE LIEN OVH !) ---
# Exemple d'URL : http://basilevinet.com/data/BaseFFE.xls
FFE_DATA_URL = "http://basilevinet.com/data/BaseFFE.xls" 

# --- CONFIGURATION ---
st.set_page_config(page_title="♟️ MasterCoach", layout="wide", page_icon="♟️")

# --- PERSISTENCE (Sauvegarde des Liaisons) ---
MAPPINGS_FILE = "mappings.json"

@st.cache_data
def load_mappings():
    # Tente de charger les mappings existants
    try:
        if os.path.exists(MAPPINGS_FILE):
             with open(MAPPINGS_FILE, "r", encoding="utf-8") as f:
                 return json.load(f)
        else:
             return {}
    except json.JSONDecodeError:
        st.warning("Fichier mappings.json vide ou mal formé. Création d'un nouveau fichier.")
        return {}
    except Exception as e:
        st.error(f"Erreur lors du chargement des mappings : {e}")
        return {}

def save_mappings(mappings_dict):
    # Sauvegarde les mappings dans le fichier JSON
    try:
        with open(MAPPINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(mappings_dict, f, indent=4)
    except Exception as e:
        st.error(f"Erreur lors de la sauvegarde des liaisons : {e}")
        
# --- FONCTION DE CHARGEMENT PERMANENT PAR URL (Lecture XLS/XLSX) ---
@st.cache_data
def load_permanent_ffe_data(url):
    try:
        all_sheets = pd.read_excel(url, sheet_name=None)
        
        df_joueurs = all_sheets.get("joueur")
        df_clubs = all_sheets.get("club")     
        
        if df_joueurs is None or df_clubs is None:
             st.error("Erreur: Impossible de trouver les feuilles nommées 'joueur' et 'club' dans le fichier Excel.")
             return pd.DataFrame()
        
        # 1. Nettoyage et combinaison des noms de joueurs (Nom Prenom)
        df_joueurs['Nom Joueur'] = df_joueurs['Nom'].str.upper() + ' ' + df_joueurs['Prenom'].str.title()
        
        # 2. Renommage des colonnes des clubs pour la jointure
        df_clubs = df_clubs.rename(columns={'Ref': 'ClubRef', 'Nom': 'Nom Club'})
        df_clubs = df_clubs[['ClubRef', 'Nom Club']]
        
        # 3. Jointure des joueurs et des noms de clubs
        df_final = pd.merge(df_joueurs, df_clubs, on='ClubRef', how='left')
        
        # 4. Conversion du ClubRef en entier
        df_final['ClubRef'] = pd.to_numeric(df_final['ClubRef'], errors='coerce').astype('Int64')
        
        # 5. Sélection et renommage des colonnes finales
        df_final = df_final[['Nom Joueur', 'Cat', 'Elo', 'ClubRef', 'Nom Club']].copy()
        df_final = df_final.rename(columns={'Nom Joueur': 'Nom'}) 
        
        st.sidebar.success(f"{len(df_final)} joueurs chargés et joints avec les clubs.")
        return df_final
        
    except Exception as e:
        st.error(f"Erreur de chargement de la base FFE. Vérifiez l'URL et le nom des onglets ('joueur', 'club'). Détail: {e}")
        return pd.DataFrame()

# --- FONCTIONS D'ANALYSE (LICHESS et SNOOPCHESS) ---
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
            # Ajout d'une vérification pour l'encodage et les types
            ouverture = str(row['Ouverture']).encode('latin-1', 'replace').decode('latin-1')
            frequence = str(row['Fréquence']).encode('latin-1', 'replace').decode('latin-1')
            pdf.cell(0, 8, f"- {ouverture} ({frequence})", ln=True)
    else:
        pdf.cell(0, 8, "Pas assez de donnees.", ln=True)
    pdf.ln(5)
    
    pdf.set_font("Arial", 'B', 14)
    pdf.cell(0, 10, "AVEC LES NOIRS (Il defend...)", ln=True)
    pdf.set_font("Arial", size=11)
    if df_black is not None and not df_black.empty:
        for index, row in df_black.iterrows():
            ouverture = str(row['Ouverture']).encode('latin-1', 'replace').decode('latin-1')
            frequence = str(row['Fréquence']).encode('latin-1', 'replace').decode('latin-1')
            pdf.cell(0, 8, f"- {ouverture} ({frequence})", ln=True)
    else:
        pdf.cell(0, 8, "Pas assez de donnees.", ln=True)
    pdf.ln(10)
    
    pdf.set_font("Arial", 'B', 12)
    pdf.cell(0, 10, "NOTES DU COACH :", ln=True)
    pdf.set_fill_color(240, 240, 240)
    pdf.rect(x=10, y=pdf.get_y(), w=190, h=60, style='F')
    
    return pdf.output(dest='S').encode('latin-1')

def get_player_stats(username, nb_games=50):
    # Analyse Lichess via API (fiable)
    url = f"https://lichess.org/api/games/user/{username}?max={nb_games}&opening=true"
    headers = {"Accept": "application/x-ndjson"}
    try:
        response = requests.get(url, headers=headers, timeout=10)
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

def extract_openings_from_html(container):
    if not container:
        return pd.DataFrame({'Ouverture': [], 'Fréquence': []})

    data = []
    # Snoopchess utilise souvent des divs spécifiques pour structurer les ouvertures
    # Cette sélection est basée sur l'observation de la structure HTML au moment de l'écriture
    rows = container.find_all('div', class_='text-sm') 
    
    for row in rows[:5]: 
        # Tente de trouver le nom de l'ouverture (souvent dans un span)
        opening_name = row.find('span', class_='text-gray-500')
        
        # Tente d'extraire la fréquence (le pourcentage) dans l'élément voisin ou enfant
        frequency_div = row.find('div', class_='w-1/4')
        
        if opening_name and frequency_div:
            data.append({
                'Ouverture': opening_name.text.strip(),
                'Fréquence': frequency_div.text.strip()
            })
    
    return pd.DataFrame(data)

def get_snoopchess_stats(username):
    # Analyse SnoopChess via Web Scraping (fragile)
    url = f"https://snoopchess.com/snoop/lichess/{username}"
    
    try:
        # User-Agent pour simuler un navigateur réel (réduit le risque de blocage)
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(url, headers=headers, timeout=15)
        
        if response.status_code != 200:
            st.warning(f"SnoopChess a retourné le statut {response.status_code}. Les données n'ont pas pu être lues.")
            return None, None
        
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Le scraping est très spécifique à la structure actuelle du site.
        white_container = soup.find('div', id='white')
        df_w = extract_openings_from_html(white_container)
        
        black_container = soup.find('div', id='black')
        df_b = extract_openings_from_html(black_container)

        return df_w, df_b
        
    except requests.exceptions.RequestException as e:
        st.warning(f"Impossible de contacter SnoopChess (Timeout/Connexion). Détail: {e}")
        return None, None


# --- MAIN APP ---
if 'mappings' not in st.session_state:
    st.session_state['mappings'] = load_mappings() 

st.title("♟️ MasterCoach - Manager")

# CHARGEMENT PERMANENT DE LA BASE FFE
df = load_permanent_ffe_data(FFE_DATA_URL)

with st.sidebar:
    st.subheader("Configuration du Club")
    
    if not df.empty:
        df_clubs_map = df[['ClubRef', 'Nom Club']].drop_duplicates().dropna(subset=['Nom Club'])
        club_name_to_id = pd.Series(df_clubs_map['ClubRef'].values, 
                                    index=df_clubs_map['Nom Club']).to_dict()
        club_names = sorted(club_name_to_id.keys())
        default_index = 0
        try:
             # Logic to set a default club index if needed
             pass
        except:
             pass

        selected_club_name = st.selectbox(
            "Nom du Club à filtrer", 
            club_names, 
            index=default_index
        )
        
        club_id = club_name_to_id.get(selected_club_name)
        st.caption(f"ID Club sélectionné : {club_id}")
        
    else:
        st.error("Base FFE non chargée.")
        club_id = 0


# --- Affichage du Contenu Principal ---
if not df.empty and club_id:
    # FILTRAGE FINAL PAR L'ID RÉCUPÉRÉ
    club_players = df[df['ClubRef'] == club_id]
    
    if not club_players.empty:
        
        # --- PREPARATION DES DONNÉES (Normalisation des catégories et Tri FFE) ---
        df_display = club_players.copy()
        df_display['Cat_Clean'] = df_display['Cat'].astype(str).str.upper().str[:3]
        
        ALL_TARGET_CODES = ["PPO", "POU", "PUP", "BEN", "MIN", "CAD", "JUN"] 
        target_codes_youth = ["PPO", "POU", "PUP", "BEN", "MIN"] 
        
        cat_order = {code: i for i, code in enumerate(ALL_TARGET_CODES)}
        df_display['Sort_Order'] = df_display['Cat_Clean'].map(cat_order).fillna(999) 
        
        df_youth = df_display[df_display['Cat_Clean'].isin(target_codes_youth)].copy()
        df_youth = df_youth.sort_values(by=['Sort_Order', 'Elo'], ascending=[True, False])
        
        # ==========================================================
        # 🚀 SECTION EN HAUT DE PAGE : TOP JOUEUR PAR CATÉGORIE
        # ==========================================================
        
        st.subheader(f"🥇 Les Meilleurs Jeunes du Club : {selected_club_name}")
        
        cols = st.columns(len(target_codes_youth))
        
        for i, code in enumerate(target_codes_youth):
            with cols[i]:
                labels = {"PPO": "P. Poussin", "POU": "Poussin", "PUP": "Pupille", "BEN": "Benjamin", "MIN": "Minime"}
                label_nice = labels.get(code, code)
                
                best = df_display[df_display['Cat_Clean'] == code].nlargest(1, 'Elo')
                
                st.markdown(f"**{label_nice}**")
                if not best.empty:
                    best_player = best.iloc[0]
                    player_name = str(best_player['Nom']) if pd.notna(best_player['Nom']) else "Nom Inconnu"
                    
                    st.metric(label=player_name, value=f"{best_player['Elo']}")
                else:
                    st.caption("-")
        
        st.markdown("---") 

        # ==========================================================
        # DÉBUT DES ONGLETS
        # ==========================================================
        
        t1, t2, t3 = st.tabs(["📋 Équipe", "🔗 Liaison Lichess", "⚔️ Prépa Match"])
        
        with t1:
            st.header(f"Détail de l'Effectif ({len(club_players)} Joueurs)")
            
            # --- Affichage 1: Top 4 par Catégorie (Tableaux) ---
            st.subheader("👶 Top 4 Joueurs Jeunes (Minimes et moins)")
            
            if not df_youth.empty:
                cols_per_row = 3
                
                for i, code in enumerate(target_codes_youth): 
                    labels = {"PPO": "P. Poussin", "POU": "Poussin", "PUP": "Pupille", "BEN": "Benjamin", "MIN": "Minime"}
                    label_nice = labels.get(code, code)
                    
                    top_4 = df_youth[df_youth['Cat_Clean'] == code].nlargest(4, 'Elo')
                    
                    if not top_4.empty:
                        if i % cols_per_row == 0:
                            if i > 0:
                                st.markdown("---")
                            cols = st.columns(cols_per_row)
                            
                        with cols[i % cols_per_row]: 
                            st.markdown(f"**{label_nice}**")
                            st.dataframe(
                                top_4[['Nom', 'Elo']],
                                column_config={"Nom": "Nom", "Elo": st.column_config.NumberColumn("ELO", format="%d")},
                                hide_index=True,
                                height=(4 * 35) + 30
                            )

            else:
                st.warning("Aucun jeune (P. Poussin à Minime) trouvé dans l'effectif actuel.")
                st.info("Catégories brutes détectées :")
                st.write(club_players['Cat'].unique())
                
            st.divider()

            # --- Affichage 2: Effectif Complet du Club ---
            st.subheader("📚 Effectif Complet du Club")
            
            df_full_sorted = df_display.sort_values(by=['Sort_Order', 'Elo'], ascending=[True, False])
            
            st.dataframe(df_full_sorted[['Nom', 'Cat', 'Elo', 'Nom Club']], hide_index=True)
        
        with t2:
            st.header("🔗 Liaison Lichess")
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
            st.header("⚔️ Préparation de Match")
            targets = [p for p in club_players['Nom'] if p in st.session_state['mappings']]
            
            if targets:
                tgt = st.selectbox("Cible (Joueur de votre club)", targets)
                pseudo = st.session_state['mappings'][tgt]
                
                # --- NOUVEAU : Affichage du lien direct ici ---
                st.markdown(f"**Analyse Externe :** [Consulter la page de {pseudo} sur SnoopChess](https://snoopchess.com/snoop/lichess/{pseudo})")
                st.markdown("---")
                
                analysis_type = st.radio("Source de l'Analyse", ["Lichess (API Officielle)", "SnoopChess (Web Scraping)"], horizontal=True)
                
                if st.button("Analyser le Répertoire"):
                    
                    if analysis_type == "Lichess (API Officielle)":
                        st.subheader("Analyse Lichess (Jeu Récent)")
                        df_w, df_b = get_player_stats(pseudo)
                        
                    elif analysis_type == "SnoopChess (Web Scraping)":
                        st.subheader("Analyse SnoopChess (Répertoire Ciblé)")
                        st.warning("⚠️ L'analyse SnoopChess est basée sur du Web Scraping et peut être lente ou échouer si le site change.")
                        df_w, df_b = get_snoopchess_stats(pseudo)
                        
                    
                    if df_w is not None and not df_w.empty:
                        c1, c2 = st.columns(2)
                        with c1: 
                            st.write("Blancs"); st.dataframe(df_w, hide_index=True)
                        with c2: 
                            st.write("Noirs"); st.dataframe(df_b, hide_index=True)
                        
                        pdf = create_pdf_download(tgt, pseudo, df_w, df_b)
                        st.download_button("📄 Télécharger PDF de Prépa", pdf, "prepa_match.pdf", "application/pdf")
                    else:
                        st.error("Impossible de récupérer ou de traiter les données pour l'analyse sélectionnée.")
                        
            else:
                st.warning("Liez d'abord un pseudo Lichess dans l'onglet 2 pour ce joueur avant de lancer l'analyse.")

# Message d'avertissement initial si l'URL est le placeholder
else: 
     st.warning("⚠️ Veuillez remplacer VOTRE_URL_STABLE_OVH_ICI par l'URL de votre fichier FFE hébergé.")



