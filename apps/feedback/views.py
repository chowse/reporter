from django.conf import settings
from django.core.exceptions import ValidationError
from django import http
from django.shortcuts import get_object_or_404
from django.views.decorators.cache import never_cache
from django.views.decorators.vary import vary_on_headers

import jingo
from tower import ugettext as _

from feedback import OPINION_PRAISE, OPINION_ISSUE, OPINION_SUGGESTION
from input.decorators import cache_page
from input.urlresolvers import reverse
from .forms import PraiseForm, IssueForm, SuggestionForm
from .models import Opinion
from .utils import detect_language
from .validators import validate_ua


def enforce_user_agent(f):
    """
    View decorator enforcing feedback from the latest beta users only.

    Can be disabled with settings.ENFORCE_USER_AGENT = False.
    """
    def wrapped(request, *args, **kwargs):
        # Validate User-Agent request header.
        ua = request.META.get('HTTP_USER_AGENT', None)
        try:
            validate_ua(ua)
        except ValidationError:
            if request.method == 'GET':
                return http.HttpResponseRedirect(reverse('feedback.need_beta'))
            else:
                return http.HttpResponseBadRequest(
                    _('User-Agent request header must be set.'))

        # if we made it here, it's a latest beta user
        return f(request, ua=ua, *args, **kwargs)

    return wrapped


@enforce_user_agent
@never_cache
def give_feedback(request, ua, type):
    """Submit feedback page"""

    Formtype = PraiseForm
    if type == OPINION_PRAISE:
        Formtype = PraiseForm
    elif type == OPINION_ISSUE:
        Formtype = IssueForm
    elif type == OPINION_SUGGESTION:
        Formtype = SuggestionForm

    if request.method == 'POST':
        form = Formtype(request.POST)
        if form.is_valid():
            # Remove URL if checkbox disabled.
            if not form.cleaned_data.get('add_url', False):
                form.cleaned_data['url'] = ''

            locale = detect_language(request)

            # Save to the DB.
            new_opinion = Opinion(
                type=type,
                url=form.cleaned_data.get('url', ''),
                description=form.cleaned_data['description'],
                user_agent=ua, locale=locale,
                manufacturer=form.cleaned_data['manufacturer'],
                device=form.cleaned_data['device'])
            new_opinion.save()

            return http.HttpResponseRedirect(reverse('feedback.thanks'))

    else:
        # URL is fed in by the feedback extension.
        url = request.GET.get('url', '')
        form = Formtype(initial={'url': url, 'add_url': False, 'type': type})

    # Set the div id for css styling
    div_id = 'feedbackform'
    if type == OPINION_SUGGESTION:
        div_id = 'suggestionform'

    url_suggestion = request.GET.get('url', 'suggestion')
    data = {
        'form': form,
        'type': type,
        'div_id': div_id,
        'MAX_FEEDBACK_LENGTH': settings.MAX_FEEDBACK_LENGTH,
        'OPINION_PRAISE': OPINION_PRAISE,
        'OPINION_ISSUE': OPINION_ISSUE,
        'OPINION_SUGGESTION': OPINION_SUGGESTION,
        'url_suggestion': url_suggestion
    }
    template = ('feedback/mobile/feedback.html' if request.mobile_site else
                'feedback/feedback.html')
    return jingo.render(request, template, data)


@vary_on_headers('User-Agent')
@enforce_user_agent
@cache_page
def feedback(request, ua):
    """The index page for feedback, which shows links to the happy and sad
      feedback pages.
    """
    template = 'feedback/%sindex.html' % (
        'mobile/' if request.mobile_site else '')
    return jingo.render(request, template)


@cache_page
def need_beta(request):
    """Encourage people to download a current beta version."""

    template = 'feedback/%sneed_beta.html' % (
        'mobile/' if request.mobile_site else '')
    return jingo.render(request, template)


@cache_page
def thanks(request):
    """Thank you for your feedback."""

    template = 'feedback/%sthanks.html' % (
        'mobile/' if request.mobile_site else '')
    return jingo.render(request, template)


@cache_page
def opinion_detail(request, id):
    o = get_object_or_404(Opinion, pk=id)
    return jingo.render(request, 'feedback/opinion.html', {'opinion': o})
