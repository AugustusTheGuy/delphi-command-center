"""Splash screen with quadrant paint animation."""

import streamlit as st


def render_splash(show: bool = True) -> None:
    if not show:
        return
    st.markdown(
        """
        <div class="dhc-splash-wrap" id="dhc-splash">
          <div class="dhc-splash-brand">Delphi Technologies</div>
          <div class="dhc-quadrant-grid dhc-q-cross">
            <div class="dhc-q-line-h"></div>
            <div class="dhc-q-line-v"></div>
            <div class="dhc-q-symbol dhc-q-tl">✖</div>
            <div class="dhc-q-symbol dhc-q-tr">÷</div>
            <div class="dhc-q-symbol dhc-q-bl">−</div>
            <div class="dhc-q-symbol dhc-q-br">➕</div>
          </div>
        </div>
        <script>
          setTimeout(function() {
            var el = document.getElementById('dhc-splash');
            if (el) { el.style.opacity = '0'; el.style.transition = 'opacity 0.6s'; }
            setTimeout(function() { if (el) el.remove(); }, 700);
          }, 2800);
        </script>
        """,
        unsafe_allow_html=True,
    )