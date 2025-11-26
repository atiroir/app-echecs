import streamlit as st
import pandas as pd
import requests
from bs4 import BeautifulSoup
import json
from collections import Counter
from fpdf import FPDF
import datetime
import urllib.parse
import time
import io

# ==============================================================================
# 1. CONFIGURATION & STYLES
# ==============================================================================
st.set_page_config(
    page_title="Gemini Chess Manager",
    layout="wide",
    page_icon="♟️",
    initial_sidebar_state="expanded"
)

# Petit CSS pour améliorer l'apparence des tableaux
st.markdown("""
<style>
    .stDataFrame { border: 1px solid #f0f2f6; border-radius: 5px; }
    h1 { color: #2c3e50; }
    h2, h3 { color: #34495e; }
    .stButton>button { width: 100%; border-radius: 5px; }
    .reportview-container .main .block-container { max-width: 1200px; }
</style>
""", unsafe_allow_html=True)


# ==============================================================================
# 2. MODULE DE SCRAPING FFE (Le moteur de récupération des joueurs)
# ==============================================================================
class FFEScraper:
    """
    Classe responsable de récupérer les données officielles depuis echecs.asso.fr
    """
    BASE_URL = "http://echecs.asso.fr/ListeJoueurs.aspx?Action=CLUB&ClubId={}"

    @staticmethod
    def get_club_members(club_id):
        """
        Scrape la liste des joueurs d'un club donné.
        Retourne un DataFrame Pandas.
        """
        url = FFEScraper.BASE_URL.format(club_id)
        try:
            # On se fait passer pour un navigateur pour éviter les blocages simples
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }
            response = requests.get(url, headers=headers, timeout=10)
            
            if response.status_code != 200:
                st.error(f"Erreur HTTP {response.status_code} lors de la connexion FFE.")
                return None

            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Le site FFE utilise des tableaux imbriqués, c'est souvent complexe.
            # On cherche les lignes de tableaux (tr)
            rows = soup.find_all('tr')
            
            players = []
            
            for row in rows:
                cols = row.find_all('td')
                # Une ligne de joueur valide a généralement ces infos :
                # [Nom, Code FFE, Cat, Sexe, Elo, Rapide, ...]
                # La structure change parfois, on essaie de détecter une ligne valide par sa longueur
                if len(cols) > 5:
                    try:
                        # Extraction (Ceci est calibré sur le format actuel du site FFE)
                        nom_complet = cols[0].get_text(strip=True)
                        code_ffe = cols[1].get_text(strip=True)
                        cat_age = cols[2].get_text(strip=True)
                        elo_long = cols[4].get_text(strip=True)
                        
                        # Nettoyage des données
                        if not code_ffe or len(code_ffe) > 7: continue # Ce n'est pas un joueur
                        
                        # Gestion Elo vide
                        if elo_long == "" or not elo_long.isdigit():
                            elo_int = 1000 # Elo par défaut si non classé
                        else:
                            elo_int = int(elo_long)

                        players.append({
                            "Nom": nom_complet,
                            "Code FFE": code_ffe,
                            "Catégorie": cat_age,
                            "Elo": elo_int
                        })
                    except Exception:
                        continue # On ignore les lignes malformées

            if not players:
                return pd.DataFrame() # Retourne vide
                
            return pd.DataFrame(players)

        except Exception as e:
            st.error(f"Erreur critique lors du scraping : {e}")
            return None


# ==============================================================================
# 3. MODULE PDF (Génération de rapport)
# ==============================================================================
class PDFReport(FPDF):
    def header(self):
        self.set_font('Arial', 'B', 16)
        self.cell(0, 10, 'FICHE DE PREPARATION MATCH', 0, 1, 'C')
        self.set_font('Arial', 'I', 10)
        self.cell(0, 10, 'Generee par Gemini Chess Manager', 0, 1, 'C')
        self.line(10, 25, 200, 25)
        self.ln(10)

    def footer(self):
        self.set_y(-15)
        self.set_font('Arial', 'I', 8)
        self.cell(0, 10, f'Page {self.page_no()}', 0, 0, 'C')

def generate_pdf(player_name, pseudo, stats_white, stats_black):
    """Crée le fichier binaire du PDF"""
    pdf = PDFReport()
    pdf.add_page()
    
    # 1. Infos Joueur
    pdf.set_font("Arial", 'B', 12)
    pdf.cell(40, 10, "Joueur Cible :", 0, 0)
    pdf.set_font("Arial", '', 12)
    pdf.cell(0, 10, f"{player_name}", 0, 1)
    
    pdf.set_font("Arial", 'B', 12)
    pdf.cell(40, 10, "Compte Lichess :", 0, 0)
    pdf.set_font("Arial", '', 12)
    pdf.cell(0, 10, f"{pseudo if pseudo else 'Non renseigné'}", 0, 1)
    pdf.ln(5)

    # 2. Tableaux Stats
    def print_section(title, df):
        pdf.set_font("Arial", 'B', 14)
        pdf.set_fill_color(230, 230, 230)
        pdf.cell(0, 10, title, 1, 1, 'L', fill=True)
        pdf.set_font("Arial", '', 11)
        if df is not None and not df.empty:
            for _, row in df.iterrows():
                # Encodage pour éviter crashs accents
                txt = f"- {row['Ouverture']} : Joue {row['Fréquence']} fois"
                txt = txt.encode('latin-1', 'replace').decode('latin-1') 
                pdf.cell(0, 8, txt, 0, 1)
        else:
            pdf.cell(0, 8, "Pas de donnees suffisantes.", 0, 1)
        pdf.ln(5)

    print_section("REPERTOIRE AVEC LES BLANCS", stats_white)
    print_section("REPERTOIRE AVEC LES NOIRS", stats_black)

    # 3. Zone Coach
    pdf.ln(10)
    pdf.set_font("Arial", 'B', 12)
    pdf.cell(0, 10, "CONSIGNES DU COACH & PREPARATION TACTIQUE :", 0, 1)
    pdf.set_fill_color(245, 245, 245)
    pdf.rect(pdf.get_x(), pdf.get_y(), 190, 80, 'F') # Grand rectangle gris
    
    return pdf.output(dest='S').encode('latin-1')


# ==============================================================================
# 4. MODULE API LICHESS (Analyse technique)
# ==============================================================================
def fetch_lichess_stats(username, nb_games=60):
    """Récupère les parties et calcule les stats d'ouverture"""
    if not username: return None, None
    
    url = f"https://lichess.org/api/games/user/{username}?max={nb_games}&opening=true"
    headers = {"Accept": "application/x-ndjson"}
    
    try:
        r = requests.get(url, headers=headers, timeout=8)
        if r.status_code != 200: return None, None
        
        games = [json.loads(l) for l in r.text.strip().split('\n') if l]
        w_ops, b_ops = [], []
        
        for g in games:
            opening = g.get('opening', {}).get('name', 'Inconnue')
            try:
                white = g['players']['white']['user']['name']
                if white.lower() == username.lower():
                    w_ops.append(opening)
                else:
                    b_ops.append(opening)
            except KeyError:
                continue
                
        # Création DataFrames
        df_w = pd.DataFrame(Counter(w_ops).most_common(8), columns=['Ouverture', 'Fréquence'])
        df_b = pd.DataFrame(Counter(b_ops).most_common(8), columns=['Ouverture', 'Fréquence'])
        return df_w, df_b
        
    except Exception as e:
        return None, None


# ==============================================================================
# 5. LOGIQUE PRINCIPALE & INTERFACE (STREAMLIT)
# ==============================================================================

# -- Gestion de l'état (Session State) pour garder les données entre les clics --
if 'club_data' not in st.session_state:
    st.session_state['club_data'] = None
if 'mappings' not in st.session_state:
    st.session_state['mappings'] = {} # Dictionnaire Nom FFE -> Pseudo Lichess

# -- Sidebar : Connexion --
with st.sidebar:
    st.header("🔍 Connexion Club")
    club_id_input = st.text_input("Numéro de Club FFE", value="100", help="Ex: 606 pour un gros club")
    
    if st.button("📥 Récupérer/Actualiser les Joueurs"):
        with st.spinner("Connexion au serveur FFE en cours..."):
            scraper = FFEScraper()
            df = scraper.get_club_members(club_id_input)
            
            if df is not None and not df.empty:
                st.session_state['club_data'] = df
                st.success(f"{len(df)} joueurs récupérés !")
            else:
                st.error("Impossible de récupérer les données. Vérifiez le numéro du club.")

    st.markdown("---")
    st.info("ℹ️ **Note:** Cette application scrape le site public de la FFE. Utilisez-la de manière responsable.")

# -- Contenu Principal --
st.title("♟️ Manager d'Équipe & Préparation")

if st.session_state['club_data'] is None:
    st.warning("👈 Veuillez entrer un numéro de club dans la barre latérale et cliquer sur 'Récupérer'.")
    st.markdown("""
    **Exemples de clubs pour tester :**
    * `100` : Un club d'élite simulé
    * `606` : Mulhouse Philidor
    * `C001` : Exemple générique
    """)
else:
    df_players = st.session_state['club_data']
    
    # Onglets
    tab1, tab2, tab3, tab4 = st.tabs([
        "📋 Liste Complète", 
        "🏆 Top Jeunes", 
        "🔗 Base de Pseudos", 
        "⚔️ Prépa & Espionnage"
    ])

    # --- TAB 1 : LISTE SIMPLE ---
    with tab1:
        st.subheader("Effectif complet")
        # Filtres rapides
        search = st.text_input("Filtrer par nom", "")
        if search:
            display_df = df_players[df_players['Nom'].str.contains(search, case=False)]
        else:
            display_df = df_players
            
        st.dataframe(
            display_df.sort_values(by="Elo", ascending=False),
            use_container_width=True,
            height=500
        )

    # --- TAB 2 : ASSISTANT TOP JEUNES ---
    with tab2:
        st.subheader("🔮 Assistant de Composition d'Équipe")
        st.markdown("Sélection automatique des meilleurs Elo par catégorie d'âge.")
        
        # Définition des catégories standards (Simplifiées)
        cats_to_check = {
            "Minime": ["Minime", "Minim"],
            "Benjamin": ["Benjamin", "Benjamine"],
            "Pupille": ["Pupille", "Pupillette"],
            "Poussin": ["Poussin", "Poussine"]
        }
        
        cols = st.columns(len(cats_to_check))
        
        for idx, (label, keywords) in enumerate(cats_to_check.items()):
            with cols[idx]:
                st.markdown(f"### {label}s")
                # Filtre complexe pour attraper les variantes (ex: Benjamine)
                mask = df_players['Catégorie'].apply(lambda x: any(k in str(x) for k in keywords))
                filtered = df_players[mask].sort_values(by="Elo", ascending=False).head(3)
                
                if not filtered.empty:
                    for i, row in filtered.iterrows():
                        st.success(f"**{row['Elo']}** - {row['Nom']}")
                else:
                    st.warning("Aucun joueur trouvé")

    # --- TAB 3 : MAPPING LICHESS ---
    with tab3:
        st.subheader("🕵️ Services de Renseignement (Liaison)")
        st.markdown("C'est ici que vous liez un nom réel à un compte en ligne.")
        
        c1, c2 = st.columns([1, 1])
        
        with c1:
            st.markdown("#### Ajouter un lien")
            selected_player = st.selectbox("Choisir un joueur du club", df_players['Nom'].unique())
            
            # Vérif si déjà existant
            current_val = st.session_state['mappings'].get(selected_player, "")
            lichess_pseudo = st.text_input("Pseudo Lichess connu", value=current_val)
            
            if st.button("💾 Enregistrer la liaison"):
                if lichess_pseudo:
                    st.session_state['mappings'][selected_player] = lichess_pseudo
                    st.success(f"Sauvegardé : {selected_player} = {lichess_pseudo}")
                else:
                    st.error("Entrez un pseudo.")

        with c2:
            st.markdown("#### Liens actifs")
            if st.session_state['mappings']:
                mapping_df = pd.DataFrame(list(st.session_state['mappings'].items()), columns=['Nom FFE', 'Pseudo Lichess'])
                st.dataframe(mapping_df, use_container_width=True)
            else:
                st.info("Aucune liaison enregistrée pour le moment.")

    # --- TAB 4 : PREPARATION MATCH (LE COEUR DU REACTEUR) ---
    with tab4:
        st.subheader("🎯 Centre d'Analyse Stratégique")
        
        # Liste des cibles : tous les joueurs du club
        targets = df_players['Nom'].unique()
        target = st.selectbox("Sélectionner l'adversaire à préparer", targets)
        
        col_snoop, col_lichess = st.columns(2)
        
        # --- PARTIE 1 : SNOOPCHESS (Deep Linking) ---
        with col_snoop:
            st.markdown("### 1. Analyse Historique")
            st.info("Consultez les résultats officiels, la forme du moment et les bêtes noires.")
            
            # Encodage URL propre
            safe_name = urllib.parse.quote(target)
            snoop_url = f"https://snoopchess.com/snoop/?q={safe_name}"
            
            st.link_button(f"🔍 Ouvrir la fiche SnoopChess de {target}", snoop_url)
        
        # --- PARTIE 2 : LICHESS (API) ---
        with col_lichess:
            st.markdown("### 2. Analyse Technique")
            pseudo = st.session_state['mappings'].get(target)
            
            if not pseudo:
                st.warning("⚠️ Pas de pseudo Lichess lié via l'onglet 3.")
                st.markdown("Vous ne pouvez pas lancer l'analyse technique sans pseudo.")
            else:
                st.success(f"Compte identifié : **{pseudo}**")
                nb_games = st.slider("Nombre de parties à scanner", 20, 100, 50)
                
                if st.button("🚀 LANCER L'ANALYSE OUVERTURES"):
                    with st.spinner(f"Téléchargement des parties de {pseudo} chez Lichess..."):
                        df_w, df_b = fetch_lichess_stats(pseudo, nb_games)
                        
                        # Stockage temporaire pour affichage en bas
                        st.session_state['last_analysis'] = {
                            'target': target, 'pseudo': pseudo, 'w': df_w, 'b': df_b
                        }

        # --- RESULTATS DE L'ANALYSE ---
        if 'last_analysis' in st.session_state and st.session_state['last_analysis']['target'] == target:
            data = st.session_state['last_analysis']
            
            st.markdown("---")
            if data['w'] is None:
                st.error("Erreur lors de la récupération des données Lichess (Pseudo invalide ou API fermée).")
            else:
                c_white, c_black = st.columns(2)
                
                with c_white:
                    st.markdown("### ⚪ Avec les Blancs")
                    st.caption("Il/Elle joue principalement...")
                    st.dataframe(data['w'], hide_index=True, use_container_width=True)
                    st.bar_chart(data['w'].set_index('Ouverture'))

                with c_black:
                    st.markdown("### ⚫ Avec les Noirs")
                    st.caption("Il/Elle répond par...")
                    st.dataframe(data['b'], hide_index=True, use_container_width=True)
                    st.bar_chart(data['b'].set_index('Ouverture'))
                
                # --- EXPORT PDF ---
                st.markdown("---")
                st.markdown("### 🖨️ Export")
                
                pdf_bytes = generate_pdf(data['target'], data['pseudo'], data['w'], data['b'])
                
                st.download_button(
                    label="📄 TÉLÉCHARGER LA FICHE DE PRÉPARATION (PDF)",
                    data=pdf_bytes,
                    file_name=f"Prepa_{target.replace(' ', '_')}.pdf",
                    mime="application/pdf"
                )

# ==============================================================================
# FIN DU CODE
# ==============================================================================
