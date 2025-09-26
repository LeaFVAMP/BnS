# app/utils/pdf.py
from flask import current_app, render_template
from pathlib import Path
from weasyprint import HTML, CSS

def render_pdf(template_name: str, out_rel_path: str, **context) -> str:
    """
    Renderiza un template HTML a PDF y lo guarda bajo instance/out_rel_path.
    Retorna la ruta absoluta.
    """
    # base: <proyecto>/instance
    base_dir = Path(current_app.instance_path)
    out_path = base_dir / out_rel_path
    out_path.parent.mkdir(parents=True, exist_ok=True)

    html = render_template(template_name, **context)
    HTML(string=html, base_url=current_app.root_path).write_pdf(
        out_path.as_posix(),
        stylesheets=[CSS(string="""
            @page { size: A4; margin: 18mm 15mm; }
            body { font-family: -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Arial; font-size: 11pt; }
            h1,h2,h3 { margin: 0 0 6px; }
            table { width: 100%; border-collapse: collapse; }
            th, td { border: 1px solid #ddd; padding: 4px 6px; }
            th { background: #f5f5f5; }
            .muted { color: #666; }
            .right { text-align: right; }
            .small { font-size: 10pt; }
        """)]
    )
    return out_path.as_posix()
