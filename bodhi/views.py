import json

from pyramid.view import view_config, notfound_view_config
from pyramid.httpexceptions import HTTPNotFound
from pyramid.security import effective_principals
from cornice import Service
from sqlalchemy.sql import or_

from . import log, buildsys
from .models import Bug, Build, CVE, Package, Release, Update, UpdateType, UpdateStatus
from .schemas import ListUpdateSchema, SaveUpdateSchema
from .security import packagers_allowed_acl, admin_only_acl
from .validators import (validate_nvrs, validate_version, validate_uniqueness,
        validate_tags, validate_acls, validate_builds, validate_enums,
        validate_releases, validate_username)


updates = Service(name='updates', path='/updates/',
                  description='Update submission service',
                  acl=packagers_allowed_acl)


@updates.get(schema=ListUpdateSchema,
             validators=(validate_releases, validate_enums, validate_username))
def query_updates(request):
    db = request.db
    data = request.validated
    query = db.query(Update)

    approved_since = data.get('approved_since')
    if approved_since is not None:
        query = query.filter(Update.date_approved >= approved_since)

    bugs = data.get('bugs')
    if bugs is not None:
        query = query.join(Update.bugs)
        query = query.filter(or_(*[Bug.bug_id==bug_id for bug_id in bugs]))

    critpath = data.get('critpath')
    if critpath is not None:
        query = query.filter_by(critpath=critpath)

    cves = data.get('cves')
    if cves is not None:
        query = query.join(Update.cves)
        query = query.filter(or_(*[CVE.cve_id==cve_id for cve_id in cves]))

    locked = data.get('locked')
    if locked is not None:
        query = query.filter_by(locked=locked)

    modified_since = data.get('modified_since')
    if modified_since is not None:
        query = query.filter(Update.date_modified >= modified_since)

    packages = data.get('packages')
    if packages is not None:
        query = query.join(Update.builds).join(Build.package)
        query = query.filter(or_(*[Package.name==pkg for pkg in packages]))

    pushed = data.get('pushed')
    if pushed is not None:
        query = query.filter_by(pushed=pushed)

    pushed_since = data.get('pushed_since')
    if pushed_since is not None:
        query = query.filter(Update.date_pushed >= pushed_since)

    qa_approved = data.get('qa_approved')
    if qa_approved is not None:
        query = query.filter_by(qa_approved=qa_approved)

    qa_approved_since = data.get('qa_approved_since')
    if qa_approved_since is not None:
        query = query.filter(Update.qa_approval_date >= qa_approved_since)

    releases = data.get('releases')
    if releases is not None:
        query = query.filter(or_(*[Update.release==r for r in releases]))

    releng_approved = data.get('releng_approved')
    if releng_approved is not None:
        query = query.filter_by(releng_approved=releng_approved)

    releng_approved_since = data.get('releng_approved_since')
    if releng_approved_since is not None:
        query = query.filter(Update.releng_approval_date >= releng_approved_since)

    req = data.get('request')
    if req is not None:
        query = query.filter_by(request=req)

    security_approved = data.get('security_approved')
    if security_approved is not None:
        query = query.filter_by(security_approved=security_approved)

    security_approved_since = data.get('security_approved_since')
    if security_approved_since is not None:
        query = query.filter(Update.security_approval_date >= security_approved_since)

    severity = data.get('severity')
    if severity is not None:
        query = query.filter_by(severity=severity)

    status = data.get('status')
    if status is not None:
        query = query.filter_by(status=status)

    submitted_since = data.get('submitted_since')
    if submitted_since is not None:
        query = query.filter(Update.date_submitted >= submitted_since)

    suggest = data.get('suggest')
    if suggest is not None:
        query = query.filter_by(suggest=suggest)

    type = data.get('type')
    if type is not None:
        query = query.filter_by(type=type)

    user = data.get('user')
    if user is not None:
        query = query.filter(Update.user==user)

    return dict(updates=[u.__json__() for u in query])


@updates.post(schema=SaveUpdateSchema, permission='create',
        validators=(validate_nvrs, validate_version, validate_builds,
                    validate_uniqueness, validate_tags, validate_acls,
                    validate_enums))
def new_update(request):
    """ Save an update.

    This entails either creating a new update, or editing an existing one. To
    edit an existing update, the update's original title must be specified in
    the ``edited`` parameter.
    """
    data = request.validated
    log.debug('validated = %s' % request.validated)

    try:
        if data.get('edited'):
            log.info('Editing update: %s' % data['edited'])
            up = Update.edit(request, data)
        else:
            log.info('Creating new update: %s' % ' '.join(data['builds']))
            up = Update.new(request, data)
            log.debug(up)
    except:
        log.exception('An unexpected exception has occured')
        request.errors.add('body', 'builds', 'Unable to create update')
        return

    # Set request
    # Send out email notifications

    return up.__json__()


@notfound_view_config(append_slash=True)
def notfound_view(context, request):
    """ Automatically redirects to slash-appended routes.

    http://docs.pylonsproject.org/projects/pyramid/en/latest/narr/urldispatch.html#redirecting-to-slash-appended-rou
    """
    return HTTPNotFound()


@view_config(route_name='home', renderer='home.html')
def home(request):
    return {}


@view_config(route_name='metrics', renderer='metrics.html')
def metrics(request):
    db = request.db
    data = []
    ticks = []
    update_types = {
        'bugfix': 'Bug fixes', 'enhancement': 'Enhancements',
        'security': 'Security updates', 'newpackage': 'New packages'
    }
    releases = db.query(Release).filter(Release.name.like('F%')).all()
    for i, release in enumerate(sorted(releases, cmp=lambda x, y:
            cmp(int(x.version_int), int(y.version_int)))):
        ticks.append([i, release.name])
    for update_type, label in update_types.items():
        d = []
        type = UpdateType.from_string(update_type)
        for i, release in enumerate(releases):
            num = db.query(Update).filter_by(release=release, type=type,
                                             status=UpdateStatus.stable).count()
            d.append([i, num])
        data.append(dict(data=d, label=label))
    return {'data': json.dumps(data), 'ticks': json.dumps(ticks)}


def get_all_packages():
    """ Get a list of all packages in Koji """
    log.debug('Fetching list of all packages...')
    koji = buildsys.get_session()
    return [pkg['package_name'] for pkg in koji.listPackages()]


@view_config(route_name='search_pkgs', renderer='json', request_method='GET')
def search_pkgs(request):
    """ Called by the NewUpdateForm.builds AutocompleteWidget """
    packages = get_all_packages()
    return [{'id': p, 'label': p, 'value': p} for p in packages
            if request.GET['term'] in p]


@view_config(route_name='latest_candidates', renderer='json')
def latest_candidates(request):
    """
    For a given `package`, this method returns the most recent builds tagged
    into the Release.candidate_tag for all Releases.
    """
    result = []
    koji = request.koji
    db = request.db
    pkg = request.params.get('package')
    log.debug('latest_candidate(%r)' % pkg)
    if pkg:
        koji.multicall = True
        for release in db.query(Release).all():
            koji.listTagged(release.candidate_tag, package=pkg, latest=True)
        results = koji.multiCall()
        for build in results:
            if build and build[0] and build[0][0]:
                result.append(build[0][0]['nvr'])
    log.debug(result)
    return result


admin_service = Service(name='admin', path='/admin/',
                        description='Administrator view',
                        acl=admin_only_acl)

@admin_service.get(permission='admin')
def admin(request):
    user = request.user
    log.info('%s logged into admin panel' % user.name)
    principals = effective_principals(request)
    return {'user': user.name, 'principals': principals}