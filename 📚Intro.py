import streamlit as st

# --- Page Config: Tab Title & Icon ---
st.set_page_config(
    page_title="Ink Chain",
    page_icon="https://explorer.inkonchain.com/assets/configs/network_icon.svg",
    layout="wide"
)

# --- Title with Logo ---
st.markdown(
    """
    <div style="display: flex; align-items: center; gap: 15px;">
        <img src="https://img.cryptorank.io/coins/ink1729850762329.png" alt="ink" style="width:60px; height:60px;">
        <h1 style="margin: 0;">Ink Chain</h1>
    </div>
    """,
    unsafe_allow_html=True
)

# --- Description Box (same color tone as logo) ---
st.markdown(
    """
    <div style="
        background-color: #E5F2FF;
        border-left: 6px solid #4A90E2;
        padding: 15px;
        border-radius: 10px;
        margin-top: 10px;
        color: #1a1a1a;
        font-size: 16px;
        line-height: 1.6;
    ">
        <b>Ink</b> is a layer 2 blockchain built on the <b>Optimism Superchain</b>, focusing on providing fast, secure, and interoperable financial solutions. 
        With features such as low gas fees, sub-second transaction speeds, and Kraken's security support, Ink aims to offer developers a robust environment for building DeFi applications.
    </div>
    """,
    unsafe_allow_html=True
)

# --- Builder Info ------------------------------------------------------------------------
st.markdown(
    """
    <div style="margin-top: 25px; font-size: 16px;">
        <div style="display: flex; align-items: center; gap: 10px;">
            <img src="https://pbs.twimg.com/profile_images/2060406047391559681/sA9zPNKM_400x400.jpg" alt="Eman Raz" style="width:25px; height:25px; border-radius: 50%;">
            <span>Built by: <a href="https://x.com/0xeman_raz" target="_blank">Eman Raz</a></span>
        </div>
    </div>

    <!-- Support / Tips Box -->
    <div style="
        background-color: #F5F5F5;
        border-left: 5px solid #888;
        padding: 12px;
        border-radius: 10px;
        margin-top: 10px;
        font-size: 15px;
        color: #333;
    ">
        🎁 <b>Support / Tips:</b><br>
        <code>0x621bd661e3d57da1c8237209824827f1027abf62</code>
    </div>
    """,
    unsafe_allow_html=True
)

# --- Sidebar Footer Slightly Left-Aligned ---
st.sidebar.markdown(
    """
    <style>
    .sidebar-footer {
        position: fixed;
        bottom: 20px;
        width: 250px;
        font-size: 13px;
        color: gray;
        margin-left: 5px; /* Move slightly left */
        text-align: left;  
    }
    .sidebar-footer img {
        width: 16px;
        height: 16px;
        vertical-align: middle;
        border-radius: 50%;
        margin-right: 5px;
    }
    .sidebar-footer a {
        color: gray;
        text-decoration: none;
    }
    </style>

    <div class="sidebar-footer">
        <div>
            <a href="https://x.com/inkonchain" target="_blank">
                <img src="https://img.cryptorank.io/coins/ink1729850762329.png" alt="Ink Logo">
                Powered by Ink
            </a>
        </div>
        <div style="margin-top: 5px;">
            <a href="https://x.com/0xeman_raz" target="_blank">
                <img src="https://pbs.twimg.com/profile_images/2060406047391559681/sA9zPNKM_400x400.jpg" alt="Eman Raz">
                Built by Eman Raz
            </a>
        </div>
    </div>
    """,
    unsafe_allow_html=True
)
