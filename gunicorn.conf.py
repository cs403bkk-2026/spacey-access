# Request log to stdout. %(U)s is the path without the query string, and the
# referer is left out, because URLs can carry values that must not be logged
# (an access code must never end up in a log line).
accesslog = "-"
access_log_format = '%(h)s %(t)s "%(m)s %(U)s %(H)s" %(s)s %(b)s %(M)sms "%(a)s"'
wsgi_app = "app:create_app()"
