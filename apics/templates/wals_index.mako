<%inherit file="${context.get('request').registry.settings.get('clld.app_template', 'app.mako')}"/>
<%namespace name="util" file="util.mako"/>
<%! active_menu_item = "apics_wals" %>
<%block name="title">APiCS - WALS</%block>

<h2>${title()}</h2>

${dt.render()}
