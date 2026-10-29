import hashlib

ORDER_FLOW = ('待备货', '待分配', '待起飞', '配送中', '已送达')
ORDER_EXCEPTIONS = ('取消',)
VEHICLE_STATES = ('可用', '装载', '飞行', '返航', '充电', '停用')

def _stable_index(text, modulo):
    if modulo <= 0:
        return 0
    return int(hashlib.sha256(text.encode('utf-8')).hexdigest()[:8], 16) % modulo

def order_id(flight):
    return f"ORD-{flight['id']}"

def vehicle_id(from_pad, scheduled_minute):
    return f"UAV-{from_pad}-{_stable_index(from_pad, 97):02}-{int(scheduled_minute) % 60:02}"

def _energy(route_km, max_altitude_agl_m, settings):
    climb = max_altitude_agl_m / 100.0 * settings['energyPercentPerClimb100m'] * 2
    return round(min(100.0, route_km * settings['energyPercentPerKm'] + climb), 2)

def evaluate(flight, settings):
    route_km = flight.get('distanceKm') or 0.0
    outbound = _energy(route_km, flight.get('maxAltitudeM') or 0.0, settings)
    inbound = _energy(route_km, flight.get('maxAltitudeM') or 0.0, settings)
    remaining = round(100.0 - outbound, 2)
    needed_to_return = round(inbound + settings['energyReservePercent'], 2)
    if remaining < needed_to_return:
        status, reason = ORDER_EXCEPTIONS[0], 'ENERGY_INSUFFICIENT_FOR_RETURN'
    elif flight['arrivalMinute'] - flight['scheduledMinute'] > settings['orderTimeoutMinutes']:
        status, reason = '已送达', 'DELIVERED_BEYOND_TARGET_WINDOW'
    else:
        status, reason = '已送达', 'ON_TIME'
    return {
        'orderId': order_id(flight),
        'vehicleId': vehicle_id(flight['fromPad'], flight['scheduledMinute']),
        'serviceNodeId': flight.get('toPad'),
        'energyPercentUsed': round(outbound + inbound, 2),
        'energyPercentRemainingAtHandover': remaining,
        'returnLegEnergyPercent': inbound,
        'energyReservePercent': settings['energyReservePercent'],
        'returnLegMinutes': round((flight['arrivalMinute'] - flight['departureMinute']), 2),
        'orderOutcome': status,
        'orderOutcomeReason': reason,
    }

def attach(flights, settings, timeline_minutes):
    delivered = cancelled = delayed = beyond = 0
    waits, outcomes = [], {}
    for flight in flights:
        if flight['mode'] != 'DELIVERY':
            continue
        if flight['status'] != 'SCHEDULED' or not flight['points']:
            flight['orderId'] = flight.get('orderId') or order_id(flight)
            flight['vehicleId'] = flight.get('vehicleId') or vehicle_id(flight['fromPad'], flight['scheduledMinute'])
            flight['orderStatus'] = flight.get('orderStatus') or '待分配'
            flight['orderOutcome'] = '取消'
            flight['orderOutcomeReason'] = flight['reason']
            flight['vehicleStatus'] = '停用'
            cancelled += 1
            outcomes[flight['reason']] = outcomes.get(flight['reason'], 0) + 1
            continue
        record = evaluate(flight, settings)
        flight.update(record)
        if flight['arrivalMinute'] > timeline_minutes:
            beyond += 1
            record['orderOutcome'] = '等待'
            record['orderOutcomeReason'] = 'ARRIVAL_BEYOND_TIMELINE'
            flight['orderStatus'] = '配送中'
        elif record['orderOutcome'] == '取消':
            cancelled += 1
        else:
            delivered += 1
        if record['orderOutcomeReason'] == 'DELIVERED_BEYOND_TARGET_WINDOW':
            delayed += 1
        waits.append(flight['delayMinutes'])
        outcomes[record['orderOutcomeReason']] = outcomes.get(record['orderOutcomeReason'], 0) + 1
    orders = delivered + cancelled + beyond
    return {
        'timelineMinutes': timeline_minutes,
        'orders': orders,
        'delivered': delivered,
        'cancelled': cancelled,
        'beyondTimeline': beyond,
        'deliveredBeyondTargetWindow': delayed,
        'deliveryRate': round(delivered / orders, 4) if orders else None,
        'timeoutRate': round(delayed / orders, 4) if orders else None,
        'averageGroundWaitMinutes': round(sum(waits) / len(waits), 2) if waits else 0.0,
        'maxGroundWaitMinutes': round(max(waits), 2) if waits else 0.0,
        'outcomeReasons': dict(sorted(outcomes.items())),
        'settings': {
            'nodesPerCity': settings['nodesPerCity'],
            'corridorsPerCity': settings['corridorsPerCity'],
            'serviceRadiusM': settings['serviceRadiusM'],
            'energyReservePercent': settings['energyReservePercent'],
            'orderTimeoutMinutes': settings['orderTimeoutMinutes'],
            'chargeMinutes': settings['chargeMinutes'],
        },
        'note': '订单与载具为模拟数据；电量为模型估计，非实测续航。',
    }

def order_state(flight, state, phase, minute):
    if flight.get('orderStatus') == '取消' or state == 'CLOSED':
        return '取消'
    if state == 'PENDING':
        return '待备货'
    if state == 'HOLD':
        return '待分配'
    if state == 'AIRBORNE':
        return '待起飞' if phase == 'CLIMB' else '配送中'
    if state == 'ARRIVED':
        return '已送达'
    return '待分配'

def vehicle_state(flight, state, minute, settings):
    if state == 'CLOSED':
        return '停用'
    if state in ('PENDING', 'HOLD'):
        return '装载'
    if state == 'AIRBORNE':
        return '飞行'
    if state == 'ARRIVED':
        settle = flight['arrivalMinute'] + (flight.get('returnLegMinutes') or 0)
        if minute < settle:
            return '返航'
        if minute < settle + settings['chargeMinutes']:
            return '充电'
        return '可用'
    return '可用'
