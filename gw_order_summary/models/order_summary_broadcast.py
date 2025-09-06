# -*- coding: utf-8 -*-
import logging
from odoo import api, models

_logger = logging.getLogger(__name__)


class StockMoveBroadcast(models.Model):
	_inherit = 'stock.move'

	def _broadcast_order_summary_update(self):
		"""used to push real-time updates from the server to connected clients"""
		bus = self.env['bus.bus']
		payload = {
			'type': 'order_summary_update',
			'move_ids': self.ids,
		}
		_logger.info(
			"BUS BROADCAST: Channel '%s', Type '%s', Payload %s",
			'order_summary_channel', 'order_summary_update', payload
		)
		bus._sendone('order_summary_channel', 'order_summary_update', payload) # sends a notification to a specific channel

	@api.model_create_multi
	def create(self, vals_list):
		records = super().create(vals_list)
		records._broadcast_order_summary_update()
		return records

	def write(self, vals):
		res = super().write(vals)
		self._broadcast_order_summary_update()
		return res

	def unlink(self):
		ids = self.ids
		res = super().unlink()
		if ids:
			self.env['bus.bus']._sendone('order_summary_channel', 'order_summary_update', {
				'type': 'order_summary_update',
				'move_ids': ids,
			})
		return res

