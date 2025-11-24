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
        # Tente de lire depuis le dossier de l'application ou le répertoire de travail
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
        # pd.read_excel lit les deux formats (.xls et .xlsx) et gère les onglets
        all_sheets = pd.read_excel(url, sheet_name=None)
        
        # S'assurer que les feuilles existent (noms attendus : joueur et club, en minuscules)
        df_joueurs = all_sheets.get("joueur")
        df_clubs = all_sheets.get("club")     
        
        if df_joueurs is None or df_clubs is None:
             # Affiche l'erreur si les onglets ne sont pas trouvés
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
        # Cette erreur s'affichera en cas d'échec du téléchargement ou d'une erreur de format
        st.error(f"Erreur de chargement de la base FFE. Vérifiez l'URL et le nom des onglets ('joueur', 'club'). Détail: {e}")
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

with st.sidebar:
    st.subheader("Configuration du Club")
    
    if not df.empty:
        # Créer un DataFrame des clubs uniques (Nom Club et ClubRef)
        df_clubs_map = df[['ClubRef', 'Nom Club']].drop_duplicates().dropna(subset=['Nom Club'])
        
        # Créer un dictionnaire Nom -> ID pour le filtrage
        club_name_to_id = pd.Series(df_clubs_map['ClubRef'].values, 
                                    index=df_clubs_map['Nom Club']).to_dict()
        
        # Créer la liste des noms pour le SelectBox (triée)
        club_names = sorted(club_name_to_id.keys())
        
        # Tenter de déterminer un index par défaut (sinon 0)
        default_index = 0
        try:
             # Tentative de cibler un club spécifique s'il existe (à changer si besoin)
             # user_club_name = df_clubs_map.loc[df_clubs_map['ClubRef'] == 999, 'Nom Club'].iloc[0]
             # default_index = club_names.index(user_club_name)
             pass
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

        # Affichage de l'ID Club (optionnel)
        st.caption(f"ID Club sélectionné : {club_id}")
        
    else:
        # Message si le chargement a échoué
        st.error("Base FFE non chargée. Vérifiez l'URL dans le code app.py.")
        club_id = 0


# --- Affichage du Contenu Principal ---
if not df.empty and club_id:
    # FILTRAGE FINAL PAR L'ID RÉCUPÉRÉ
    club_players = df[df['ClubRef'] == club_id]
    
    if not club_players.empty:
        # Définition des onglets
        t1, t2, t3 = st.tabs(["📋 Équipe", "🔗 Liaison Lichess", "⚔️ Prépa Match"])
        
        with t1:
            st.header(f"Effectif : {selected_club_name} ({len(club_players)} Joueurs)")
            
            # --- 1. Préparation des données Jeunes (Normalisation) ---
            df_display = club_players.copy()
            
            # On crée une colonne temporaire 'Cat_Clean' : on met en majuscule et on prend les 3 premières lettres
            df_display['Cat_Clean'] = df_display['Cat'].astype(str).str.upper().str[:3]
            
            # Liste des codes cibles DANS L'ORDRE FFE SOUHAITÉ (du plus jeune au plus âgé)
            # PPO: Petits Poussins, POU: Poussins, PUP: Pupilles, BEN: Benjamins, MIN: Minimes
            # J'ajoute Cadet et Junior pour l'ordre complet, même si l'affichage principal s'arrête à MIN
            ALL_TARGET_CODES = ["PPO", "POU", "PUP", "BEN", "MIN", "CAD", "JUN"] 
            
            # Codes pour l'affichage 'Minimes et moins'
            target_codes_youth = ["PPO", "POU", "PUP", "BEN", "MIN"] 
            
            # Filtrage des jeunes (Minimes et moins)
            df_youth = df_display[df_display['Cat_Clean'].isin(target_codes_youth)].copy()
            
            # --- Ajout d'une colonne pour le tri basé sur l'ordre FFE fourni ---
            # Crée un mapping Nom_code -> Ordre (PPO=0, POU=1, PUP=2, etc.)
            cat_order = {code: i for i, code in enumerate(ALL_TARGET_CODES)}
            df_youth['Sort_Order'] = df_youth['Cat_Clean'].map(cat_order)
            
            # Tri final par l'ordre FFE, puis par ELO décroissant
            df_youth = df_youth.sort_values(by=['Sort_Order', 'Elo'], ascending=[True, False])

            # --- Affichage renommé ---
            st.subheader("👶 Joueurs Jeunes (Minimes et moins)")
            
            if not df_youth.empty:
                st.markdown("### Top 4 Joueurs par Catégorie")
                
                cols_per_row = 3
                
                # Utilisation de la liste triée pour l'affichage
                for i, code in enumerate(target_codes_youth): 
                    # Définition des labels pour l'affichage
                    labels = {"PPO": "P. Poussin", "POU": "Poussin", "PUP": "Pupille", "BEN": "Benjamin", "MIN": "Minime"}
                    label_nice = labels.get(code, code)
                    
                    # On cherche le top 4 pour cette catégorie
                    top_4 = df_youth[df_youth['Cat_Clean'] == code].nlargest(4, 'Elo')
                    
                    if not top_4.empty:
                        # Créer une nouvelle ligne de colonnes après 3 catégories
                        if i % cols_per_row == 0:
                            if i > 0:
                                st.markdown("---") 
                            cols = st.columns(cols_per_row)
                            
                        with cols[i % cols_per_row]: 
                            st.markdown(f"**{label_nice}**")
                            # Afficher le tableau du top 4
                            st.dataframe(
                                top_4[['Nom', 'Elo']],
                                column_config={
                                    "Nom": "Nom",
                                    "Elo": st.column_config.NumberColumn("ELO", format="%d")
                                },
                                hide_index=True,
                                height=(4 * 35) + 30
                            )

            else:
                st.warning("Aucun jeune (P. Poussin à Minime) trouvé dans l'effectif actuel.")
                st.info("Voici les catégories brutes détectées dans votre fichier (pour diagnostic) :")
                st.write(club_players['Cat'].unique())
                
            st.divider()

            st.subheader("📚 Effectif Complet du Club")
            # Le tri du tableau complet utilise maintenant le tri FFE
            df_full_sorted = df_display.copy()
            df_full_sorted['Sort_Order'] = df_full_sorted['Cat_Clean'].map(cat_order)
            
            # Remplacer les NaN (adultes ou autres) par une valeur élevée pour les mettre à la fin
            df_full_sorted['Sort_Order'] = df_full_sorted['Sort_Order'].fillna(999) 
            
            df_full_sorted = df_full_sorted.sort_values(by=['Sort_Order', 'Elo'], ascending=[True, False])
            
            st.dataframe(df_full_sorted[['Nom', 'Cat', 'Elo', 'Nom Club', 'Sort_Order']], hide_index=True)
        
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
                st.warning("Liez d'abord un pseudo Lichess dans l'onglet 2 pour ce joueur.")
    else:
        st.error(f"Aucun joueur trouvé pour le club sélectionné.")

# Message d'avertissement initial si l'URL est le placeholder
elif FFE_DATA_URL == "VOTRE_URL_STABLE_OVH_ICI":
     st.warning("⚠️ Veuillez remplacer VOTRE_URL_STABLE_OVH_ICI par l'URL de votre fichier FFE hébergé.")

