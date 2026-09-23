"""Health tools (originally Lab 2).

ADK builds the function schema from the type hints and the docstring, so both
are part of the public contract of a tool, not decoration.
"""

from __future__ import annotations


def calculate_bmi(weight_kg: float, height_m: float) -> dict:
    """Calculates the Body Mass Index (BMI) from weight in kilograms and height in meters.

    Args:
        weight_kg: The weight of the person in kilograms (e.g. 70.0).
        height_m: The height of the person in meters (e.g. 1.75).

    Returns:
        A dict with the calculated 'bmi' value, or an 'error' message if the input is invalid.
    """
    if height_m <= 0:
        return {"error": "height_m must be greater than 0"}
    if weight_kg <= 0:
        return {"error": "weight_kg must be greater than 0"}
    return {"bmi": round(weight_kg / (height_m**2), 2)}


def get_advice(bmi: float) -> dict:
    """Classifies a BMI value and returns standard health advice for that range.

    Args:
        bmi: The Body Mass Index value (e.g. 22.8).

    Returns:
        A dict with the 'classification' of the BMI and the corresponding 'advice'.
    """
    if bmi < 18.5:
        classification = "underweight"
        advice = "Consult a nutritionist about a plan for healthy weight gain."
    elif bmi < 25.0:
        classification = "normal weight"
        advice = "Keep up the balanced diet and the active routine."
    elif bmi < 30.0:
        classification = "overweight"
        advice = "Focus on regular exercise and balanced portion sizes."
    else:
        classification = "obese"
        advice = "Seek professional guidance from a healthcare provider."
    return {"classification": classification, "advice": advice}
