import streamlit as st

# --- Page Config: Tab Title & Icon ---
st.set_page_config(
    page_title="Base Blockchain",
    page_icon="https://images.cryptorank.io/coins/150x150.base1752857325751.png",
    layout="wide"
)

# --- Title with Logo ---
st.markdown(
    """
    <div style="display: flex; align-items: center; gap: 15px;">
        <img src="https://images.cryptorank.io/coins/150x150.base1752857325751.png" alt="Base" style="width:60px; height:60px;">
        <h1 style="margin: 0;">Base Blockchain</h1>
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
        <b>Base</b> is a <b>layer 2 blockchain</b>, focusing on providing fast, low-cost, and Ethereum-secure access to onchain applications. 
        Developed by <b>Coinbase</b>, it is designed to bring mainstream users and developers onto Ethereum without the high fees and congestion of the base layer.
        With features such as low gas fees, quick transaction confirmation, full EVM compatibility, and Coinbase’s distribution and security support, <b>Base</b> aims to offer builders a
        practical environment for DeFi, consumer apps, and onchain products. Settlement and security ultimately rest on Ethereum, while day-to-day activity stays cheap and responsive on 
        the L2.
        
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
