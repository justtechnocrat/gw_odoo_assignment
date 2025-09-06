# -*- coding: utf-8 -*-
{
	'name': 'Order Summary API',
	'summary': 'JWT-protected API and websocket updates for delivery quantities',
	'Version': '18.0.1.0.0',
	'author': 'Shivank Tyagi [GW Products]',
	'website': 'https://www.gwproductsusa.com/',
	'category': 'Tools',
	'license': 'LGPL-3',
	'depends': ['base', 'sale_management', 'stock', 'bus', 'mrp'],
	'data': [
		'security/ir.model.access.csv',
		'data/ir_config_parameter.xml',
	],
	'assets': {},
	'installable': True,
	'application': False,
}

