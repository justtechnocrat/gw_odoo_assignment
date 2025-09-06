# -*- coding: utf-8 -*-
import base64
import json
import hmac
import hashlib
import time
from typing import Any, Dict

from odoo import http
from odoo.http import request


def _b64url(data: bytes) -> str:
	return base64.urlsafe_b64encode(data).rstrip(b'=').decode()

def _b64url_decode(data: str) -> bytes:
	pad = '=' * (-len(data) % 4)
	return base64.urlsafe_b64decode(data + pad)


def encode_jwt(payload: Dict[str, Any], secret: str) -> str:
	header = {'alg': 'HS256', 'typ': 'JWT'}
	header_b64 = _b64url(json.dumps(header, separators=(',', ':')).encode())
	payload_b64 = _b64url(json.dumps(payload, separators=(',', ':')).encode())
	signing_input = f"{header_b64}.{payload_b64}".encode()
	signature = hmac.new(secret.encode(), signing_input, hashlib.sha256).digest()
	return f"{header_b64}.{payload_b64}.{_b64url(signature)}"


def decode_jwt(token: str, secret: str) -> Dict[str, Any]:
	try:
		header_b64, payload_b64, sig_b64 = token.split('.')
		signing_input = f"{header_b64}.{payload_b64}".encode()
		expected_sig = hmac.new(secret.encode(), signing_input, hashlib.sha256).digest()
		if not hmac.compare_digest(expected_sig, _b64url_decode(sig_b64)):
			raise ValueError('Invalid signature')
		payload = json.loads(_b64url_decode(payload_b64))
		if 'exp' in payload and int(time.time()) > int(payload['exp']):
			raise ValueError('Token expired')
		return payload
	except Exception as exc:
		raise ValueError('Invalid token') from exc


def _get_jwt_secret_and_expiry(env):
    import pdb; pdb.set_trace()
    secret = env['ir.config_parameter'].sudo().get_param('gw_order_summary.jwt_secret', default='ItsTechnoSecret')
    expiry_seconds = int(env['ir.config_parameter'].sudo().get_param('gw_order_summary.jwt_expiry_seconds', default='900'))
    return secret, expiry_seconds


def _require_bearer_jwt(fn):
	def wrapper(*args, **kwargs):
		authz = request.httprequest.headers.get('Authorization')
		if not authz or not authz.startswith('Bearer '):
			return request.make_response(json.dumps({'error': 'missing_token'}), headers=[('Content-Type', 'application/json')], status=401)
		token = authz.split(' ', 1)[1].strip()
		try:
			secret, _ = _get_jwt_secret_and_expiry(request.env)
			payload = decode_jwt(token, secret)
			request.jwt_payload = payload  # type: ignore[attr-defined]
		except ValueError:
			return request.make_response(json.dumps({'error': 'invalid_token'}), headers=[('Content-Type', 'application/json')], status=401)
		return fn(*args, **kwargs)
	return wrapper


class OrderSummaryController(http.Controller):
	@http.route(['/api/v1/order-summary/token'], type='json', auth='none', csrf=False, methods=['POST'])
	def issue_token(self, **kwargs):
     	# import pdb; pdb.set_trace()
		env = request.env
		secret, expiry_seconds = _get_jwt_secret_and_expiry(env)
		now = int(time.time())
		payload = {
			'iat': now,
			'exp': now + expiry_seconds,
			'sub': 'order-summary',
		}
		return {'token': encode_jwt(payload, secret), 'expires_in': expiry_seconds}

	@http.route(['/api/v1/order-summary'], type='http', auth='none', csrf=False, methods=['GET'])
	@_require_bearer_jwt
	def order_summary(self, **kwargs):
		# import pdb; pdb.set_trace()
		print("===  Order Summary API Called ===")
		print(f"DEBUG:Params received:---- {request.params}")

		params = request.params
		delivery_ids = params.get('delivery_ids')
		product_templates = params.get('product_templates')
		benchmark = params.get('benchmark') in ('1', 'true', 'True')

		def _parse_list(value):
			if not value:
				return []
			if isinstance(value, (list, tuple)):
				return list(value)
			try:
				parsed = json.loads(value)
				if isinstance(parsed, list):
					return parsed
			except Exception:
				pass
			return [v for v in str(value).split(',') if v]

		delivery_ids_list = [int(v) for v in _parse_list(delivery_ids)]
		product_templates_list = [str(v) for v in _parse_list(product_templates)]

		env = request.env
		sql, args = self._build_optimized_sql(env, delivery_ids_list, product_templates_list, benchmark)
		
		print("=== DEBUG: Order Summary SQL Query ===")
		print(sql)
		print("=== DEBUG: Order Summary Parameters ===")
		print(f"Args: {args}")
		print(f"Number of parameters: {len(args)}")
		
		cr = env.cr
		cr.execute(sql, args)
		rows = cr.dictfetchall()
		return request.make_response(
			json.dumps({'rows': rows, 'count': len(rows)}),
			headers=[('Content-Type', 'application/json')],
		)

	def _build_optimized_sql(self, env, delivery_ids_list, product_templates_list, benchmark: bool):
     	# import pdb; pdb.set_trace()
		final_args: list[Any] = []
		lang = env.lang  # Get the current language from the environment

		# --- Ordered CTE parts ---
		ordered_where_clauses = ["so.state IN ('sale', 'done')"]
		ordered_params = []
		if product_templates_list:
			ordered_where_clauses.append("(pt.name->>%s) = ANY(%s::text[])")
			ordered_params.append(lang)
			ordered_params.append(product_templates_list)

		# --- Manufactured CTE parts ---
		manufactured_where_clauses = ["mp.state IN ('confirmed', 'progress', 'to_close', 'done')"]
		manufactured_params = []
		if product_templates_list:
			manufactured_where_clauses.append("(pt.name->>%s) = ANY(%s::text[])")
			manufactured_params.append(lang)
			manufactured_params.append(product_templates_list)

		# --- Delivered CTE parts ---
		delivered_where_clauses = ["sm.state = 'done'", "spt.code = 'outgoing'"]
		delivered_params = []
		if delivery_ids_list:
			delivered_where_clauses.append("sp.id = ANY(%s)")
			delivered_params.append(delivery_ids_list)
		if product_templates_list:
			delivered_where_clauses.append("(pt.name->>%s) = ANY(%s::text[])")
			delivered_params.append(lang)
			delivered_params.append(product_templates_list)

		# Combine all parameters in the exact order they appear in the SQL query
		final_args.extend(ordered_params)
		final_args.extend(manufactured_params)
		final_args.extend(delivered_params)

		explain_analyze = 'EXPLAIN ANALYZE ' if benchmark else ''

		ordered_where_clause_str = "WHERE " + " AND ".join(ordered_where_clauses) if ordered_where_clauses else ""
		manufactured_where_clause_str = "WHERE " + " AND ".join(manufactured_where_clauses) if manufactured_where_clauses else ""
		delivered_where_clause_str = "WHERE " + " AND ".join(delivered_where_clauses) if delivered_where_clauses else ""

		sql = f'''
		{explain_analyze}
		WITH ordered AS (
			SELECT
				pt.id AS product_tmpl_id,
				SUM(sol.product_uom_qty) AS ordered_qty
			FROM sale_order_line sol
			JOIN product_product pp ON pp.id = sol.product_id
			JOIN product_template pt ON pt.id = pp.product_tmpl_id
			JOIN sale_order so ON so.id = sol.order_id
			{ordered_where_clause_str}
			GROUP BY pt.id
		),
		manufactured AS (
			SELECT
				pt.id AS product_tmpl_id,
				COALESCE(SUM(mp.product_qty), 0) AS manufactured_qty
			FROM mrp_production mp
			JOIN product_product pp ON pp.id = mp.product_id
			JOIN product_template pt ON pt.id = pp.product_tmpl_id
			{manufactured_where_clause_str}
			GROUP BY pt.id
		),
		delivered AS (
			SELECT
				pt.id AS product_tmpl_id,
				COALESCE(SUM(sml.quantity), 0) AS delivered_qty
			FROM stock_move_line sml
			JOIN stock_move sm ON sm.id = sml.move_id
			JOIN stock_picking sp ON sp.id = sm.picking_id
			JOIN stock_picking_type spt ON spt.id = sp.picking_type_id
			JOIN product_product pp ON pp.id = sml.product_id
			JOIN product_template pt ON pt.id = pp.product_tmpl_id
			{delivered_where_clause_str}
			GROUP BY pt.id
		)
		SELECT
			pt.id AS product_tmpl_id,
			pt.name AS product_template_name,
			COALESCE(o.ordered_qty, 0) AS ordered_qty,
			COALESCE(m.manufactured_qty, 0) AS manufactured_qty,
			COALESCE(d.delivered_qty, 0) AS delivered_qty
		FROM product_template pt
		LEFT JOIN ordered o ON o.product_tmpl_id = pt.id
		LEFT JOIN manufactured m ON m.product_tmpl_id = pt.id
		LEFT JOIN delivered d ON d.product_tmpl_id = pt.id
		WHERE (o.ordered_qty IS NOT NULL OR m.manufactured_qty IS NOT NULL OR d.delivered_qty IS NOT NULL)
		ORDER BY pt.id
		'''
		return sql, tuple(final_args)

	@http.route(['/api/v1/order-summary/benchmark'], type='http', auth='none', csrf=False, methods=['GET'])
	@_require_bearer_jwt
	def benchmark(self, **kwargs):
		params = request.params
		delivery_ids = params.get('delivery_ids')
		product_templates = params.get('product_templates')

		def _parse_list(value):
			if not value:
				return []
			try:
				parsed = json.loads(value)
				if isinstance(parsed, list):
					return parsed
			except Exception:
				pass
			return [v for v in str(value).split(',') if v]

		delivery_ids_list = [int(v) for v in _parse_list(delivery_ids)]
		product_templates_list = [str(v) for v in _parse_list(product_templates)]

		env = request.env
		sql, args = self._build_optimized_sql(env, delivery_ids_list, product_templates_list, True)
		
		print("=== DEBUG: Benchmark SQL Query ===")
		print(sql)
		print("=== DEBUG: Benchmark Parameters ===")
		print(f"Args: {args}")
		
		cr = env.cr
		cr.execute(sql, args)
		plan = [row[0] for row in cr.fetchall()]
		return request.make_response(
			json.dumps({'plan': plan}),
			headers=[('Content-Type', 'application/json')],
		)

