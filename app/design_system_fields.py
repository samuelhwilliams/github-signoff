from wtforms import SelectField, SelectMultipleField
from wtforms.widgets import HTMLString, html_params, CheckboxInput, RadioInput


class _GovukListInputWidget(object):
    """Refactor this to be better... (mostly __call__)"""

    def __init__(self, input_type="checkboxes", prefix_label=True):
        if input_type not in {"checkboxes", "radios"}:
            raise ValueError("Must choose either `checkboxes` or `radios` as the input_type.")
        self.input_type = input_type
        self.prefix_label = prefix_label

    def __call__(self, field, **kwargs):
        kwargs.setdefault("id", field.id)

        class_ = kwargs.get("class_", "")
        if class_ and f"govuk-{self.input_type}" not in class_:
            kwargs["class_"] = kwargs.get("class_", "") + f" govuk-{self.input_type}"

        html = ["<div %s>" % html_params(**kwargs)]
        for subfield in field:
            if self.prefix_label:
                html.append(
                    f'<div class="govuk-{self.input_type}__item">%s %s</div>'
                    % (
                        subfield.label(class_=f"govuk-{self.input_type}__label"),
                        subfield(class_=f"govuk-{self.input_type}__input"),
                    )
                )
            else:
                html.append(
                    f'<div class="govuk-{self.input_type}__item">%s %s</div>'
                    % (
                        subfield(class_=f"govuk-{self.input_type}__input"),
                        subfield.label(class_=f"govuk-{self.input_type}__label"),
                    )
                )
        html.append("</div>")
        return HTMLString("".join(html))


class DSCheckboxField(SelectMultipleField):
    widget = _GovukListInputWidget(input_type="checkboxes", prefix_label=False)
    option_widget = CheckboxInput()


class DSRadioField(SelectField):
    widget = _GovukListInputWidget(input_type="radios", prefix_label=False)
    option_widget = RadioInput()
