class OutboundItem {
  final int id;
  final String content;
  final List<String> tags;
  final DateTime createdAt;
  final String? ownerUser;
  final bool closed;
  final DateTime? closedAt;

  OutboundItem({
    required this.id,
    required this.content,
    required this.tags,
    required this.createdAt,
    this.ownerUser,
    required this.closed,
    this.closedAt,
  });

  factory OutboundItem.fromJson(Map<String, dynamic> json) {
    return OutboundItem(
      id: json['id'],
      content: json['content'] ?? '',
      tags: json['tags'] != null ? List<String>.from(json['tags']) : [],
      createdAt: DateTime.parse(json['created_at']),
      ownerUser: json['owner_user'],
      closed: json['closed'] ?? false,
      closedAt: json['closed_at'] != null
          ? DateTime.parse(json['closed_at'])
          : null,
    );
  }
}

class ShopeeOrderInfo {
  final int id;
  final String? packageNumber;
  final String? logisticsStatus;
  final String? trackingNumber;
  final String? pickupCode;
  final String? note;

  ShopeeOrderInfo({
    required this.id,
    this.packageNumber,
    this.logisticsStatus,
    this.trackingNumber,
    this.pickupCode,
    this.note,
  });

  factory ShopeeOrderInfo.fromJson(Map<String, dynamic> json) {
    return ShopeeOrderInfo(
      id: json['id'],
      packageNumber: json['package_number'],
      logisticsStatus: json['logistics_status'],
      trackingNumber: json['tracking_number'],
      pickupCode: json['pickup_code'],
      note: json['note'],
    );
  }
}

class ShopeeOrderRecipient {
  final int id;
  final String? name;
  final String? city;

  ShopeeOrderRecipient({required this.id, this.name, this.city});

  factory ShopeeOrderRecipient.fromJson(Map<String, dynamic> json) {
    return ShopeeOrderRecipient(
      id: json['id'],
      name: json['name'],
      city: json['city'],
    );
  }
}

class ShopeeOrderItem {
  final int id;
  final int itemId;
  final String itemName;
  final String itemSku;
  final int? modelId;
  final String? modelName;
  final String? modelSku;
  final int modelQuantityPurchased;
  final String imageUrl;

  ShopeeOrderItem({
    required this.id,
    required this.itemId,
    required this.itemName,
    required this.itemSku,
    this.modelId,
    this.modelName,
    this.modelSku,
    required this.modelQuantityPurchased,
    required this.imageUrl,
  });

  factory ShopeeOrderItem.fromJson(Map<String, dynamic> json) {
    return ShopeeOrderItem(
      id: json['id'],
      itemId: json['item_id'],
      itemName: json['item_name'],
      itemSku: json['item_sku'] ?? 'unknown',
      modelId: json['model_id'],
      modelName: json['model_name'],
      modelSku: json['model_sku'],
      modelQuantityPurchased: json['model_quantity_purchased'],
      imageUrl: json['image_url'],
    );
  }
}

class ShopeeOrder {
  final String orderSn;
  final bool splitUp;
  final String status;
  final DateTime shipBy;
  final String? ownerUser;
  final bool done;
  final DateTime? doneAt;
  final List<ShopeeOrderItem> itemList;
  final ShopeeOrderRecipient? recipientAddress;
  final List<ShopeeOrderInfo> info;

  ShopeeOrder({
    required this.orderSn,
    required this.splitUp,
    required this.status,
    required this.shipBy,
    this.ownerUser,
    required this.done,
    this.doneAt,
    required this.itemList,
    this.recipientAddress,
    required this.info,
  });

  factory ShopeeOrder.fromJson(Map<String, dynamic> json) {
    return ShopeeOrder(
      orderSn: json['order_sn'],
      splitUp: json['split_up'] ?? false,
      status: json['status'] ?? '',
      shipBy: DateTime.parse(json['ship_by']),
      ownerUser: json['owner_user'],
      done: json['done'] ?? false,
      doneAt: json['done_at'] != null ? DateTime.parse(json['done_at']) : null,
      itemList: json['item_list'] != null
          ? List<Map<String, dynamic>>.from(
              json['item_list'],
            ).map((e) => ShopeeOrderItem.fromJson(e)).toList()
          : [],
      recipientAddress: json['recipient_address'] != null
          ? ShopeeOrderRecipient.fromJson(json['recipient_address'])
          : null,
      info: json['info'] != null
          ? List<Map<String, dynamic>>.from(
              json['info'],
            ).map((e) => ShopeeOrderInfo.fromJson(e)).toList()
          : [],
    );
  }
}

class PickItemEntry {
  final int id;
  final String sku;
  final int qty;
  final String? orderSn;
  final DateTime timestamp;
  final String ownerUser;
  final String? itemName;

  PickItemEntry({
    required this.id,
    required this.sku,
    required this.qty,
    this.orderSn,
    required this.timestamp,
    required this.ownerUser,
    this.itemName,
  });

  factory PickItemEntry.fromJson(Map<String, dynamic> json) {
    return PickItemEntry(
      id: json['id'],
      sku: json['sku'] ?? '',
      qty: json['qty'] ?? 0,
      orderSn: json['order_sn'],
      timestamp: DateTime.parse(json['timestamp']),
      ownerUser: json['owner_user'] ?? '',
      itemName: json['item_name'],
    );
  }
}

class WarehouseItem {
  final String sku;
  final String? itemName;
  final String? location;

  WarehouseItem({required this.sku, this.itemName, this.location});

  factory WarehouseItem.fromJson(Map<String, dynamic> json) {
    return WarehouseItem(
      sku: json['sku'] ?? '',
      itemName: json['item_name'],
      location: json['location'],
    );
  }
}

class Stock {
  final int id;
  final String sku;
  final int stock;
  final String? location;
  final String? itemName;

  Stock({
    required this.id,
    required this.sku,
    required this.stock,
    this.location,
    this.itemName,
  });

  factory Stock.fromJson(Map<String, dynamic> json) {
    return Stock(
      id: json['id'],
      sku: json['sku'] ?? '',
      stock: json['stock'] ?? 0,
      location: json['location'],
      itemName: json['item_name'],
    );
  }
}
