"""
Grounding validation utilities.

Extracted from report.py so they can be imported and tested
without importing LangChain (which has heavy dependencies).
"""
from typing import List, Set, Dict, Any

from app.schemas import ReportOutput, ReportSection
from app.models import Asset


def validate_report_ids(report: ReportOutput, real_ids: Set[str]) -> Dict[str, Any]:
    """
    Validate that every asset ID referenced in report sections exists in real_ids.
    Mutates the report in-place to strip hallucinated IDs from sections.

    Returns:
        {grounded: bool, hallucinated_ids: [...], flagged_sections: [...]}
    """
    hallucinated = []
    flagged_sections = []

    for section in report.sections:
        bad_ids = [rid for rid in section.referenced_asset_ids if rid not in real_ids]
        if bad_ids:
            hallucinated.extend(bad_ids)
            flagged_sections.append({
                "section": section.title,
                "hallucinated_ids": bad_ids,
            })
            # Strip hallucinated IDs in-place
            section.referenced_asset_ids = [
                rid for rid in section.referenced_asset_ids if rid in real_ids
            ]

    return {
        "grounded": len(hallucinated) == 0,
        "hallucinated_ids": list(set(hallucinated)),
        "flagged_sections": flagged_sections,
    }


def extract_mentioned_values(report: ReportOutput, real_assets: List[Asset]) -> List[str]:
    """
    Find real asset value strings that appear in the report text.
    Used for transparency (not for grounding enforcement).
    """
    all_text = report.executive_summary + " "
    for section in report.sections:
        all_text += section.title + " " + section.content + " "
    all_text += " ".join(report.key_findings)

    mentioned = []
    for asset in real_assets:
        if asset.value in all_text:
            mentioned.append(asset.value)
    return mentioned
