#!/bin/sh
# Generate the Odoo 17 module from the Odoo 18 one.
#
# WHY GENERATED AND NOT HAND-MAINTAINED
# The two versions differ in exactly four places, all of them mechanical.
# Two hand-kept copies would drift apart on the first bug fix, and the
# drift would be invisible until a customer on the older version hit it.
# So the 17.0 tree is a build artefact: change 18.0, run this, commit both.
#
#   1. <list> became the tag for list views in Odoo 18; 17 says <tree>.
#   2. view_mode uses "list" in 18 and "tree" in 17.
#   3. The web client URL scheme changed: /odoo/action-<xmlid> in 18,
#      /web#action=<xmlid> in 17.
#   4. A record URL: /odoo/contacts/<id> in 18, the #id=…&model=… form in 17.
#
# Everything else - all the Python, the cron, the security rules - is
# identical, and that is the point.

set -e

here=$(dirname "$0")/..
cd "$here"

rm -rf 17.0
mkdir -p 17.0
cp -r 18.0/webex_calling 17.0/webex_calling

# 1 + 2 - list views
find 17.0 -name '*.xml' -exec sed -i \
    -e 's/<list /<tree /g' \
    -e 's/<list>/<tree>/g' \
    -e 's|</list>|</tree>|g' \
    -e 's|<field name="view_mode">list</field>|<field name="view_mode">tree</field>|g' \
    -e 's|<field name="view_mode">list,form</field>|<field name="view_mode">tree,form</field>|g' \
    -e 's|\.list</field>|.tree</field>|g' \
    {} +

# view id suffixes, so nothing reads "list" in a 17 database
find 17.0 -name '*.xml' -exec sed -i 's/view_webex_call_list/view_webex_call_tree/g; s/view_webex_connection_list/view_webex_connection_tree/g' {} +

# 3 - action URL after the OAuth return
sed -i 's|/odoo/action-webex_calling.action_connection|/web#action=webex_calling.action_connection|' \
    17.0/webex_calling/controllers/main.py

# 4 - record URL in the lookup answer
sed -i 's|"%s/odoo/contacts/%s" % (base.rstrip("/"), partner.id)|"%s/web#id=%s\&model=res.partner\&view_type=form" % (base.rstrip("/"), partner.id)|' \
    17.0/webex_calling/controllers/main.py

# version string
sed -i 's/"version": "18\.0\./"version": "17.0./' 17.0/webex_calling/__manifest__.py

echo "17.0/webex_calling generated from 18.0/webex_calling."
