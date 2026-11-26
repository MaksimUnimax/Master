def step_page(req, result=None, error="", status=200):
    from .web_ui import auth_document
    stage = (result or {}).get("stage")
    title, body, label = STEPS.get(stage, ("Начните вход заново", "Срок действия подтверждения истёк или вход ещё не начат.", ""))
    if stage == "bind":
        body = "Укажите адрес для подтверждения. Данные вашей мастерской останутся в аккаунте."
    message = f'<p role="alert" class="error">{escape(error)}</p>' if error else ""
    key = (f'<div class="auth-key-box"><p class="auth-key-label">Ключ для приложения-аутентификатора</p><code class="auth-key">{escape(result["setup_key"])}</code></div>' if stage == "setup" else "")
    field = ('type="email" maxlength="254" autocomplete="email"' if stage == "bind" else
             'class="auth-code" type="text" inputmode="numeric" pattern="[0-9]{6}" maxlength="6" autocomplete="one-time-code"')
    form = (f'<form method="post" action="/auth/verify"><label>{label}<input name="value" {field} required autofocus></label>'
            '<button type="submit">Продолжить</button></form>') if stage else ""
    resend = ('<form method="post" action="/auth/resend"><button class="secondary">Отправить код ещё раз</button></form>' if stage == "email" else "")
    return auth_document(title, f'<p class="auth-desc">{escape(body)}</p>{key}{message}{form}{resend}<a class="pm-auth-back" href="/login">Вернуться ко входу</a>', status=status)
