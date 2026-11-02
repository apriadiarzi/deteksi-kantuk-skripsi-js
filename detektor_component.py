import mimetypes
import os

import streamlit.components.v1 as components

# Registry Windows kadang memetakan .js ke text/plain; tanpa ini skrip komponen tidak dijalankan
# browser saat aplikasi dijalankan lokal di Windows.
mimetypes.add_type("application/javascript", ".js")

detektor_component = components.declare_component(
    "detektor",
    path=os.path.join(os.path.dirname(os.path.abspath(__file__)), "components", "detektor"),
)
