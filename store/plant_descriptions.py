from django.utils.safestring import mark_safe

# plant_descriptions.py
PLANT_DESCRIPTIONS = {
    'rose': {
    'care_points': [
        'Moderate maintenance required',
        'Water 2-3 times per week',
        'Prefers loamy, well-drained soil',
        'Needs full sunlight (6+ hrs daily)',
        'Plant in late winter or early spring',
        'Blooms in spring and early summer'
        ]
    },
    'adenium': {
    'care_points': [
        'Low maintenance, easy to grow',
        'Water once a week in summer',
        'Needs sandy, well-drained soil',
        'Prefers full sun, outdoor plant',
        'Plant in spring or early summer',
        'Blooms in summer to early fall'
        ]
    },
    'marigold': {
    'care_points': [
        'Low maintenance flowering plant',
        'Water 2-3 times per week',
        'Grows best in well-drained soil',
        'Needs full sun (6+ hours)',
        'Plant in early spring season',
        'Blooms from spring to autumn'
    ]
},
'hibiscus': {
    'care_points': [
        'Moderate maintenance required',
        'Water 3-4 times per week',
        'Needs fertile, well-drained soil',
        'Loves full sun to partial shade',
        'Plant in spring or early summer',
        'Blooms from spring to late fall'
    ]
},
'flower booster': {
    'care_points': [
        'Low effort, easy to use',
        'Apply once every 15 days',
        'Mix with water before use',
        'Use in morning or evening',
        'Avoid over-fertilizing plants',
        'Best used during blooming phase'
    ]
},
'maize seeds': {
    'care_points': [
        'Moderate care required',
        'Water every 2-3 days',
        'Needs rich, well-drained soil',
        'Prefers full sunlight daily',
        'Sow in spring or early summer',
        'Harvest in 2-3 months'
    ]
},
'cocopeat': {
    'care_points': [
        'Soak in water before use',
        'Improves soil aeration and drainage',
        'Suitable for all indoor/outdoor plants',
        'Ideal for seed germination'
    ]
},
'peanut seeds': {
    'care_points': [
        'Water every 3-4 days',
        'Needs sandy, well-drained soil',
        'Requires full sunlight exposure',
        'Sow in early summer season',
        'Harvest in 4-5 months'
    ]
},
'planter': {
    'care_points': [
        'Ensure drainage holes are open',
        'Suitable for indoor or outdoor use',
        'Choose size as per plant growth',
        'Use with potting mix or cocopeat'
    ]
},
'cactus trio': {
    'care_points': [
        'Very low maintenance plants',
        'Water once every 10-15 days',
        'Use sandy, well-draining cactus mix',
        'Place in bright sunlight or partial shade',
        'Ideal for spring and summer planting',
        'Occasional blooming in warmer months'
    ]
},
'jade': {
    'care_points': [
        'Very low maintenance required',
        'Water once every 7-10 days',
        'Needs well-drained succulent soil',
        'Prefers bright indirect sunlight',
    ]
},










}

def format_plant_help_text(plant_key):
    """Format plant description for Django admin help text"""
    if plant_key not in PLANT_DESCRIPTIONS:
        return ""
    
    plant = PLANT_DESCRIPTIONS[plant_key]
    care_points_html = ''.join([f"<li style='margin-bottom: 5px;'>{point}</li>" for point in plant['care_points']])
    
    return mark_safe(
        f"<div style='background-color: #f9f9f9; padding: 15px; border-radius: 5px; line-height: 1.6; margin-top: 10px;'>"
        f"<h4 style='color: #27ae60; margin-bottom: 10px;'>{plant_key.capitalize()} Care Information</h4>"
        f"<p style='margin-bottom: 15px; font-style: italic; color: #555;'>{plant['description']}</p>"
        f"<div style='background-color: #fff; padding: 10px; border-radius: 3px; border-left: 4px solid #27ae60;'>"
        f"<strong style='color: #2c3e50;'>Care Instructions:</strong>"
        f"<ul style='margin-top: 8px; margin-bottom: 0; padding-left: 20px; color: #555;'>"
        f"{care_points_html}"
        f"</ul>"
        f"</div>"
        f"</div>"
    )

def get_plant_names():
    """Return list of available plant names for choices"""
    return [(key, key.capitalize()) for key in PLANT_DESCRIPTIONS.keys()]