"""Identidade visual profissional de Marcela Pacheco para o app Streamlit."""
from pathlib import Path
import streamlit as st

APP_DIR = Path(__file__).resolve().parent
LOGO_PATH = APP_DIR / "design-marcela" / "assets" / "logo-mp.png"

def aplicar():
    st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Cormorant+Garamond:ital,wght@0,500;0,600;0,700;1,500&family=Hanken+Grotesk:wght@400;500;600;700&display=swap');
:root{--gold:#a3762a;--ink:#3a332a;--muted:#8a8168;--paper:#fffdf9;--cream:#f2ece0;--line:#ece2ce}
html,body,[class*="css"],[data-testid="stAppViewContainer"]{font-family:'Hanken Grotesk',system-ui,sans-serif;color:var(--ink)}
.stApp,[data-testid="stAppViewContainer"],[data-testid="stMain"],[data-testid="stMainBlockContainer"],[data-testid="stSidebar"]{color:var(--ink)!important}
.stApp p,.stApp span,.stApp div,.stApp label,.stApp li,.stApp td,.stApp th{color:inherit}
.stApp{background:radial-gradient(1300px 620px at 50% -260px,#fbf7ec,#f2ece0 70%)}
[data-testid="stHeader"]{background:transparent}
[data-testid="stMainBlockContainer"]{max-width:1220px;padding-top:2rem;padding-bottom:5rem}
[data-testid="stSidebar"]{background:rgba(255,253,249,.96);border-right:1px solid var(--line)}
[data-testid="stSidebarContent"]{padding-top:1.25rem}
h1,h2,h3{font-family:'Cormorant Garamond',Georgia,serif!important;color:var(--ink)!important;letter-spacing:.1px}
h1{font-size:clamp(2.4rem,5vw,3.35rem)!important;line-height:1.03!important}h2,h3{font-weight:600!important}
p,label,.stCaption,[data-testid="stCaptionContainer"]{color:var(--muted)!important}
[data-testid="stMarkdownContainer"],[data-testid="stText"],[data-testid="stWidgetLabel"],[data-testid="stExpander"] summary,[data-testid="stExpander"] summary span,[data-testid="stTabs"] button,[data-testid="stMetricLabel"],[data-testid="stMetricDelta"]{color:var(--ink)!important}
[data-testid="stVerticalBlockBorderWrapper"]{background:var(--paper);border-color:var(--line)!important;border-radius:18px!important;box-shadow:0 20px 44px -34px rgba(120,92,30,.45)}
div[data-baseweb="input"]>div,div[data-baseweb="select"]>div,textarea,[data-baseweb="textarea"]>div{background:#faf5ea!important;border-color:#e6dcc6!important;border-radius:11px!important;color:var(--ink)!important}
input,textarea,[data-baseweb="select"] input,[data-baseweb="select"] div,[data-baseweb="popover"] li{color:var(--ink)!important;-webkit-text-fill-color:var(--ink)!important}
input::placeholder,textarea::placeholder{color:#9a917f!important;-webkit-text-fill-color:#9a917f!important;opacity:1}
.stButton>button,.stDownloadButton>button{border-radius:12px;min-height:2.8rem;font-weight:600;border-color:#e3d3ab;color:#7a6224!important;background:#fffdf9}
.stButton>button p,.stButton>button span,.stDownloadButton>button p,.stDownloadButton>button span{color:inherit!important}
.stButton>button[kind="primary"]{background:linear-gradient(150deg,#c69c3f,#a5762a);color:#fffdf7!important;border:0;box-shadow:0 12px 24px -12px rgba(150,110,30,.6)}
.stButton>button:hover,.stDownloadButton>button:hover{border-color:#b98b32;color:#8b6421}hr{border-color:var(--line)!important}
[data-testid="stMetric"]{background:#faf5ea;border:1px solid #eee3cd;border-radius:13px;padding:.8rem 1rem}
[data-testid="stMetricValue"],[data-testid="stMetricValue"]>div{font-family:'Cormorant Garamond',Georgia,serif;color:var(--gold)!important}
[data-testid="stExpander"]{background:var(--paper);border-color:var(--line);border-radius:13px}[data-testid="stAlert"]{border-radius:11px}
.mp-brand{text-align:center;padding:.25rem 0 1rem;border-bottom:1px solid var(--line);margin-bottom:1rem}
.mp-brand-name{font:600 1.45rem/1 'Cormorant Garamond',Georgia,serif;color:var(--ink)}
.mp-brand-role{margin-top:.45rem;font-size:.62rem;font-weight:700;letter-spacing:.2rem;text-transform:uppercase;color:var(--gold)}
.mp-kicker{margin-bottom:.55rem;font-size:.68rem;font-weight:700;letter-spacing:.18rem;text-transform:uppercase;color:var(--gold)}
.mp-hero-accent{color:#9a6f22;font-style:italic}.mp-hero-copy{max-width:680px;line-height:1.65;color:var(--muted)}
.mp-flow{margin:.4rem 0 1.4rem}.mp-flow-title{margin-bottom:.55rem;font-size:.62rem;font-weight:700;letter-spacing:.12rem;text-transform:uppercase;color:#b0a68f}
.mp-step{display:flex;align-items:center;gap:.65rem;padding:.42rem .25rem;color:#8a8168;font-size:.82rem}
.mp-step-dot{width:1.45rem;height:1.45rem;display:flex;align-items:center;justify-content:center;border-radius:50%;background:#f4ead4;border:1px solid #dec58f;color:#9a6f22;font-size:.7rem;font-weight:700}
::selection{background:#e7d29a}@media(max-width:700px){[data-testid="stMainBlockContainer"]{padding-left:1rem;padding-right:1rem}h1{font-size:2.35rem!important}}
</style>
""", unsafe_allow_html=True)

def sidebar_brand():
    if LOGO_PATH.exists():
        st.sidebar.image(str(LOGO_PATH), width=120)
    st.sidebar.markdown("""
<div class="mp-brand"><div class="mp-brand-name">Marcela Pacheco</div><div class="mp-brand-role">Nutrição Clínica</div></div>
<div class="mp-flow"><div class="mp-flow-title">Fluxo clínico</div>
<div class="mp-step"><span class="mp-step-dot">1</span>Anamnese</div><div class="mp-step"><span class="mp-step-dot">2</span>Revisão e metas</div>
<div class="mp-step"><span class="mp-step-dot">3</span>Geração do cardápio</div><div class="mp-step"><span class="mp-step-dot">4</span>Validação e exportação</div></div>
""", unsafe_allow_html=True)

def hero():
    st.markdown("""
<div class="mp-kicker">Copiloto Clínico de Prescrição</div>
<h1>Do prontuário ao cardápio,<br><span class="mp-hero-accent">com precisão clínica.</span></h1>
<p class="mp-hero-copy">Cole a anamnese, a IA organiza os dados, você revisa as metas e recebe o cardápio pronto para o WebDiet — com validação de cálculos e revisão clínica em cada etapa.</p>
""", unsafe_allow_html=True)
