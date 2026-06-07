import 'package:flutter/material.dart';

// Models ----
class OutboundItem {
  final int id;
  final String content;
  final String? tag;
  final DateTime createdAt;
  final String? ownerUser;
  final bool closed;
  final DateTime? closedAt;

  OutboundItem({
    required this.id,
    required this.content,
    this.tag,
    required this.createdAt,
    this.ownerUser,
    required this.closed,
    this.closedAt,
  });

  factory OutboundItem.fromJson(Map<String, dynamic> json) {
    return OutboundItem(
      id: json['id'],
      content: json['content'] ?? '',
      tag: json['tag'],
      createdAt: DateTime.parse(json['created_at']),
      ownerUser: json['owner_user'],
      closed: json['closed'] ?? false,
      closedAt: json['closed_at'] != null
          ? DateTime.parse(json['closed_at'])
          : null,
    );
  }
}

class AdminUser {
  final int id;
  final String username;
  final String role;

  AdminUser({required this.id, required this.username, required this.role});

  factory AdminUser.fromJson(Map<String, dynamic> json) {
    return AdminUser(
      id: json['id'],
      username: json['username'] ?? '',
      role: json['role'] ?? 'user',
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
      status: json['status'],
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

  PickItemEntry({
    required this.id,
    required this.sku,
    required this.qty,
    this.orderSn,
    required this.timestamp,
    required this.ownerUser,
  });

  factory PickItemEntry.fromJson(Map<String, dynamic> json) {
    return PickItemEntry(
      id: json['id'],
      sku: json['sku'] ?? '',
      qty: json['qty'] ?? 0,
      orderSn: json['order_sn'],
      timestamp: DateTime.parse(json['timestamp']),
      ownerUser: json['owner_user'] ?? '',
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

// Widgets ----

// Mimic NavigationRail
class CustomRailItem extends StatefulWidget {
  final IconData icon;
  final IconData? selectedIcon;
  final String label;
  final bool isSelected;
  final VoidCallback onTap;
  final bool isExpanded;

  // Final Touch Properties
  final NavigationRailLabelType labelType;
  final Color? backgroundColor;
  final IconThemeData? selectedIconTheme;
  final TextStyle? selectedLabelTextStyle;

  const CustomRailItem({
    super.key,
    required this.icon,
    this.selectedIcon,
    required this.label,
    required this.isSelected,
    required this.onTap,
    this.isExpanded = false,
    this.labelType = NavigationRailLabelType.none, // Default to none
    this.backgroundColor,
    this.selectedIconTheme,
    this.selectedLabelTextStyle,
  });

  @override
  State<CustomRailItem> createState() => _CustomRailItemState();
}

class _CustomRailItemState extends State<CustomRailItem> {
  bool _isHovered = false;

  bool get _shouldShowLabel {
    // If the rail is extended, the label is ALWAYS shown.
    if (widget.isExpanded) return true;

    // Logic for compact mode based on NavigationRailLabelType
    switch (widget.labelType) {
      case NavigationRailLabelType.none:
        return false;
      case NavigationRailLabelType.selected:
        return widget.isSelected;
      case NavigationRailLabelType.all:
        return true;
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final activeIcon = widget.isSelected
        ? (widget.selectedIcon ?? widget.icon)
        : widget.icon;

    final labelStyle = widget.isSelected
        ? (widget.selectedLabelTextStyle?.copyWith(fontSize: 14.0) ??
              TextStyle(
                color: theme.colorScheme.primary,
                fontWeight: FontWeight.bold,
                fontSize: 12,
              ))
        : TextStyle(
            color: theme.colorScheme.onSurfaceVariant,
            fontWeight: FontWeight.w500,
            fontSize: 12,
          );

    return MouseRegion(
      onEnter: (_) => setState(() => _isHovered = true),
      onExit: (_) => setState(() => _isHovered = false),
      cursor: SystemMouseCursors.click,
      child: InkWell(
        onTap: widget.onTap,
        hoverColor: Colors.transparent,
        highlightColor: Colors.transparent,
        splashColor: theme.colorScheme.primary.withValues(alpha: 0.1),
        borderRadius: BorderRadius.circular(32),
        // 1. Wrap the transition in an AnimatedSwitcher for smooth cross-fading
        child: AnimatedSwitcher(
          duration: const Duration(milliseconds: 200),
          switchInCurve: Curves.easeInOut,
          switchOutCurve: Curves.easeInOut,
          child: widget.isExpanded
              ? _buildExtended(activeIcon, labelStyle, theme)
              : _buildCompact(activeIcon, labelStyle, theme),
        ),
      ),
    );
  }

  Widget _buildExtended(
    IconData activeIcon,
    TextStyle labelStyle,
    ThemeData theme,
  ) {
    return Align(
      key: const ValueKey('extended'),
      alignment: Alignment.centerLeft, // Anchor to the left side
      child: Row(
        mainAxisSize: MainAxisSize.max,
        children: [
          _buildIndicator(activeIcon, theme),
          // 2. Wrap text in Flexible + ClipRect + Align to prevent RenderFlex
          Flexible(
            child: ClipRect(
              child: Align(
                alignment: Alignment.centerLeft,
                widthFactor:
                    1.0, // Allows child to size infinitely, but visually clips it
                child: Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    const SizedBox(width: 12),
                    Text(
                      widget.label,
                      style: labelStyle,
                      overflow: TextOverflow.ellipsis,
                      maxLines: 1,
                    ),
                    const SizedBox(
                      width: 12,
                    ), // Add trailing space to avoid rubbing edge
                  ],
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildCompact(
    IconData activeIcon,
    TextStyle labelStyle,
    ThemeData theme,
  ) {
    return Align(
      key: const ValueKey('compact'),
      alignment: Alignment.centerLeft, // Keep anchored to the left
      child: SizedBox(
        width:
            80.0, // 3. Force to closed width so it matches extended indicator exactly
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            _buildIndicator(activeIcon, theme),
            if (_shouldShowLabel) ...[
              const SizedBox(height: 4),
              Text(
                widget.label,
                style: labelStyle,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
              ),
            ],
          ],
        ),
      ),
    );
  }

  Widget _buildIndicator(IconData activeIcon, ThemeData theme) {
    Color pillColor = Colors.transparent;
    if (widget.isSelected) {
      pillColor =
          widget.backgroundColor ?? theme.colorScheme.secondaryContainer;
    } else if (_isHovered) {
      pillColor = theme.colorScheme.onSurfaceVariant.withValues(alpha: 0.08);
    }

    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 12.0, vertical: 4.0),
      child: Stack(
        alignment: Alignment.center,
        children: [
          AnimatedContainer(
            duration: const Duration(milliseconds: 200),
            width: 56,
            height: 32,
            decoration: BoxDecoration(
              color: pillColor,
              borderRadius: BorderRadius.circular(16),
            ),
          ),
          AnimatedSwitcher(
            duration: const Duration(milliseconds: 200),
            child: Icon(
              activeIcon,
              key: ValueKey<bool>(widget.isSelected),
              color: widget.isSelected
                  ? theme.colorScheme.onSecondaryContainer
                  : theme.colorScheme.onSurfaceVariant,
              size: widget.isSelected ? widget.selectedIconTheme?.size : null,
            ),
          ),
        ],
      ),
    );
  }
}
