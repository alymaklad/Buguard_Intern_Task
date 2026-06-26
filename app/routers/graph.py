from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlmodel import Session, select

from app.db import get_session
from app.models import Asset, AssetRelationship
from app.auth import get_current_tenant
from app.limiter import limiter

router = APIRouter(prefix="/graph", tags=["Visualization"])

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Asset Relationship Graph</title>
    <script type="module">
        import mermaid from 'https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.esm.min.mjs';
        mermaid.initialize({ startOnLoad: true, theme: 'dark' });
    </script>
    <style>
        body {
            background-color: #1e1e1e;
            color: #ffffff;
            font-family: sans-serif;
            margin: 0;
            padding: 20px;
        }
        .mermaid {
            display: flex;
            justify-content: center;
            margin-top: 20px;
        }
    </style>
</head>
<body>
    <h2>Asset Graph Visualization</h2>
    <div class="mermaid">
        {mermaid_code}
    </div>
</body>
</html>
"""

@router.get("/visualize", response_class=HTMLResponse)
@limiter.limit("5/minute")
def visualize_graph(
    request: Request,
    tenant_id: str = Depends(get_current_tenant),
    session: Session = Depends(get_session)
):
    """
    Renders an HTML page with a Mermaid.js flowchart of all assets and relationships
    for the current tenant.
    """
    assets = session.exec(select(Asset).where(Asset.tenant_id == tenant_id)).all()
    rels = session.exec(select(AssetRelationship).where(AssetRelationship.tenant_id == tenant_id)).all()

    if not assets:
        return HTMLResponse("<body><h2>No assets found for this tenant.</h2></body>")

    # Build Mermaid graph
    lines = ["flowchart TD"]
    
    # Define nodes
    for a in assets:
        # Sanitize values to avoid Mermaid syntax errors
        safe_val = a.value.replace('"', '').replace(" ", "_")
        lines.append(f'    node_{a.id.replace("-", "")}["{safe_val}\\n({a.type.value})"]')
        
    # Define edges
    for r in rels:
        src = f'node_{r.from_asset_id.replace("-", "")}'
        dst = f'node_{r.to_asset_id.replace("-", "")}'
        rel_label = r.relationship_type.value
        lines.append(f'    {src} -- "{rel_label}" --> {dst}')

    mermaid_code = "\n".join(lines)
    html_content = HTML_TEMPLATE.replace("{mermaid_code}", mermaid_code)
    
    return HTMLResponse(content=html_content)
