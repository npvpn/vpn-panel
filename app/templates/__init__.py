from datetime import datetime

import jinja2

from config import resolved_custom_templates_directory, resolved_subscription_templates_dir

from .filters import CUSTOM_FILTERS

template_directories = ["app/templates"]
custom_templates_directory = resolved_custom_templates_directory()
if custom_templates_directory:
    # User's templates have priority over default templates
    template_directories.insert(0, custom_templates_directory)
# Каталог страниц подписки — чтобы рендерить `limited.html`, а не `subscription/limited.html`.
subscription_templates_dir = resolved_subscription_templates_dir()
if subscription_templates_dir:
    template_directories.insert(0, str(subscription_templates_dir))

env = jinja2.Environment(loader=jinja2.FileSystemLoader(template_directories))
env.filters.update(CUSTOM_FILTERS)
env.globals["now"] = datetime.utcnow


def render_template(template: str, context: dict | None = None) -> str:
    return env.get_template(template).render(context or {})
