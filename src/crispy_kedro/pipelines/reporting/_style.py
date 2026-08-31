"""Global matplotlib/seaborn plotting style for the reporting stage.

Imported for its side effects by every plotting module in this package so the
style is applied on import, exactly as it was when all plots lived in
``nodes.py``.
"""

import matplotlib.pyplot as plt
import seaborn as sns

# Set plotting style
plt.style.use("seaborn-v0_8")
sns.set_palette("husl")
