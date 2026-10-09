"""Formulários base com o estilo do design system (máscaras BRL, CPF/CNPJ, datas)."""

from django import forms
from django.db import models


class EstiloMixin:
    """Aplica classes CSS, máscaras e localização (aceita colar "1.234,56")."""

    campos_doc: tuple[str, ...] = ("cpf_cnpj", "cnpj", "cpf")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from . import contexto

        empresa = contexto.empresa_atual()
        for nome, campo in self.fields.items():
            qs = getattr(campo, "queryset", None)
            if qs is not None and empresa is not None and hasattr(qs.model, "empresa_id") \
                    and qs.model.__name__ != "Usuario":
                campo.queryset = qs.filter(empresa=empresa)
            w = campo.widget
            classes = w.attrs.get("class", "")
            if isinstance(w, forms.CheckboxInput):
                w.attrs["class"] = f"{classes} checkbox".strip()
                continue
            if isinstance(w, forms.CheckboxSelectMultiple):
                w.attrs["class"] = f"{classes} checklist".strip()
                continue
            if isinstance(w, forms.Select | forms.SelectMultiple):
                w.attrs["class"] = f"{classes} input select".strip()
            else:
                w.attrs["class"] = f"{classes} input".strip()
            if isinstance(campo, forms.DecimalField):
                campo.localize = True
                w.is_localized = True
                w.input_type = "text"
                w.attrs.setdefault("inputmode", "decimal")
                w.attrs.setdefault("data-mask", "money")
                w.attrs["class"] += " mono num"
            if isinstance(campo, forms.DateTimeField) and not isinstance(w, forms.HiddenInput):
                campo.widget = forms.DateTimeInput(attrs={**w.attrs, "type": "datetime-local"},
                                                   format="%Y-%m-%dT%H:%M")
                campo.input_formats = ["%Y-%m-%dT%H:%M", "%d/%m/%Y %H:%M"]
            elif isinstance(campo, forms.DateField) and not isinstance(w, forms.HiddenInput):
                campo.widget = forms.DateInput(attrs={**w.attrs, "type": "date"}, format="%Y-%m-%d")
                campo.input_formats = ["%Y-%m-%d", "%d/%m/%Y"]
            if nome in self.campos_doc:
                from django.core.validators import MaxLengthValidator

                campo.max_length = 18
                campo.validators = [v for v in campo.validators if not isinstance(v, MaxLengthValidator)]
                w.attrs["maxlength"] = 18
                w.attrs.setdefault("data-mask", "doc")
                w.attrs["class"] += " mono"
            if nome == "cep":
                w.attrs.setdefault("data-mask", "cep")
            if isinstance(w, forms.Textarea):
                w.attrs.setdefault("rows", 4)


class FormKS(EstiloMixin, forms.ModelForm):
    def _clean_fields(self):
        super()._clean_fields()
        from .validadores import so_digitos

        for nome in self.campos_doc:
            if nome in self.cleaned_data and isinstance(self.cleaned_data[nome], str):
                self.cleaned_data[nome] = so_digitos(self.cleaned_data[nome])


class FormSimples(EstiloMixin, forms.Form):
    pass


def campos_editaveis(model, excluir=()):
    base = {"id", "empresa", "criado_em", "atualizado_em", "criado_por"}
    nomes = []
    for f in model._meta.get_fields():
        if f.auto_created or not getattr(f, "editable", False) or f.name in base or f.name in excluir:
            continue
        if isinstance(f, models.ManyToOneRel | models.ManyToManyRel | models.OneToOneRel):
            continue
        nomes.append(f.name)
    return nomes
