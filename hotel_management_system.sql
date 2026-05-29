/*
 Navicat Premium Dump SQL

 Source Server         : mysql80
 Source Server Type    : MySQL
 Source Server Version : 80044 (8.0.44)
 Source Host           : localhost:3306
 Source Schema         : hotel_management_system

 Target Server Type    : MySQL
 Target Server Version : 80044 (8.0.44)
 File Encoding         : 65001

 Date: 28/05/2026 14:10:03
*/

SET NAMES utf8mb4;
SET FOREIGN_KEY_CHECKS = 0;

-- ----------------------------
-- Table structure for checkin
-- ----------------------------
DROP TABLE IF EXISTS `checkin`;
CREATE TABLE `checkin`  (
  `checkin_id` int NOT NULL AUTO_INCREMENT COMMENT '入住记录编号',
  `room_id` int NOT NULL COMMENT '房间号',
  `cust_id` int NOT NULL COMMENT '客户编号',
  `checkin_time` datetime NOT NULL COMMENT '入住时间',
  `actual_checkout_time` datetime NULL DEFAULT NULL COMMENT '实际退房时间',
  `operator` varchar(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci NULL DEFAULT NULL COMMENT '经办人',
  PRIMARY KEY (`checkin_id`) USING BTREE,
  INDEX `idx_checkin_room`(`room_id` ASC) USING BTREE,
  INDEX `idx_checkin_cust`(`cust_id` ASC) USING BTREE,
  INDEX `idx_checkin_operator`(`operator` ASC) USING BTREE,
  CONSTRAINT `checkin_ibfk_1` FOREIGN KEY (`room_id`) REFERENCES `room` (`room_id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT `checkin_ibfk_2` FOREIGN KEY (`cust_id`) REFERENCES `customer` (`cust_id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT `checkin_ibfk_3` FOREIGN KEY (`operator`) REFERENCES `users` (`username`) ON DELETE RESTRICT ON UPDATE RESTRICT
) ENGINE = InnoDB AUTO_INCREMENT = 7 CHARACTER SET = utf8mb4 COLLATE = utf8mb4_general_ci COMMENT = '入住登记表' ROW_FORMAT = Dynamic;

-- ----------------------------
-- Records of checkin
-- ----------------------------

-- ----------------------------
-- Table structure for checkout
-- ----------------------------
DROP TABLE IF EXISTS `checkout`;
CREATE TABLE `checkout`  (
  `checkout_id` int NOT NULL AUTO_INCREMENT COMMENT '退房记录编号',
  `room_id` int NOT NULL COMMENT '房间号',
  `cust_id` int NOT NULL COMMENT '客户编号',
  `checkout_time` datetime NOT NULL COMMENT '退房时间',
  `total_fee` decimal(10, 2) NULL DEFAULT NULL COMMENT '总费用',
  `extra_fee` decimal(10, 2) NULL DEFAULT 0.00 COMMENT '额外费用',
  PRIMARY KEY (`checkout_id`) USING BTREE,
  INDEX `idx_checkout_room`(`room_id` ASC) USING BTREE,
  INDEX `idx_checkout_cust`(`cust_id` ASC) USING BTREE,
  CONSTRAINT `checkout_ibfk_1` FOREIGN KEY (`room_id`) REFERENCES `room` (`room_id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT `checkout_ibfk_2` FOREIGN KEY (`cust_id`) REFERENCES `customer` (`cust_id`) ON DELETE RESTRICT ON UPDATE RESTRICT
) ENGINE = InnoDB AUTO_INCREMENT = 5 CHARACTER SET = utf8mb4 COLLATE = utf8mb4_general_ci COMMENT = '退房结算表' ROW_FORMAT = Dynamic;

-- ----------------------------
-- Records of checkout
-- ----------------------------

-- ----------------------------
-- Table structure for customer
-- ----------------------------
DROP TABLE IF EXISTS `customer`;
CREATE TABLE `customer`  (
  `cust_id` int NOT NULL AUTO_INCREMENT COMMENT '客户编号',
  `name` varchar(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci NOT NULL COMMENT '客户姓名',
  `phone_encrypted` varbinary(256) NOT NULL COMMENT '加密后的联系方式',
  PRIMARY KEY (`cust_id`) USING BTREE
) ENGINE = InnoDB AUTO_INCREMENT = 8 CHARACTER SET = utf8mb4 COLLATE = utf8mb4_general_ci COMMENT = '客户信息表' ROW_FORMAT = Dynamic;

-- ----------------------------
-- Records of customer
-- ----------------------------

-- ----------------------------
-- Table structure for operation_log
-- ----------------------------
DROP TABLE IF EXISTS `operation_log`;
CREATE TABLE `operation_log`  (
  `log_id` int NOT NULL AUTO_INCREMENT COMMENT '日志编号',
  `operator` varchar(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci NULL DEFAULT NULL COMMENT '操作人',
  `operation_type` varchar(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci NULL DEFAULT NULL COMMENT '操作类型',
  `detail` text CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci NULL COMMENT '详细描述',
  `log_time` datetime NULL DEFAULT CURRENT_TIMESTAMP COMMENT '操作时间',
  `ip_address` varchar(45) CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci NULL DEFAULT NULL COMMENT 'IP地址',
  PRIMARY KEY (`log_id`) USING BTREE,
  INDEX `idx_log_time`(`log_time` ASC) USING BTREE
) ENGINE = InnoDB AUTO_INCREMENT = 51 CHARACTER SET = utf8mb4 COLLATE = utf8mb4_general_ci COMMENT = '系统操作日志表' ROW_FORMAT = Dynamic;

-- ----------------------------
-- Records of operation_log
-- ----------------------------
INSERT INTO `operation_log` VALUES (47, 'root@localhost', '客房状态变更', '房间101状态从已预订变为空闲', '2026-05-27 22:14:44', NULL);
INSERT INTO `operation_log` VALUES (48, 'root@localhost', '客房状态变更', '房间103状态从清洁中变为空闲', '2026-05-27 22:14:44', NULL);
INSERT INTO `operation_log` VALUES (49, 'root@localhost', '客房状态变更', '房间105状态从维修中变为空闲', '2026-05-27 22:14:44', NULL);
INSERT INTO `operation_log` VALUES (50, 'root@localhost', '客房状态变更', '房间106状态从清洁中变为空闲', '2026-05-27 22:14:44', NULL);

-- ----------------------------
-- Table structure for reservation
-- ----------------------------
DROP TABLE IF EXISTS `reservation`;
CREATE TABLE `reservation`  (
  `res_id` int NOT NULL AUTO_INCREMENT COMMENT '预订编号',
  `room_id` int NOT NULL COMMENT '房间号',
  `cust_id` int NOT NULL COMMENT '客户编号',
  `checkin_date` date NOT NULL COMMENT '计划入住日期',
  `status` enum('已预订','已取消') CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci NULL DEFAULT '已预订' COMMENT '预订状态',
  `created_at` datetime NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  PRIMARY KEY (`res_id`) USING BTREE,
  INDEX `idx_res_cust_status`(`cust_id` ASC, `status` ASC) USING BTREE,
  INDEX `idx_res_room_date`(`room_id` ASC, `checkin_date` ASC) USING BTREE,
  CONSTRAINT `reservation_ibfk_1` FOREIGN KEY (`room_id`) REFERENCES `room` (`room_id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT `reservation_ibfk_2` FOREIGN KEY (`cust_id`) REFERENCES `customer` (`cust_id`) ON DELETE RESTRICT ON UPDATE RESTRICT
) ENGINE = InnoDB AUTO_INCREMENT = 5 CHARACTER SET = utf8mb4 COLLATE = utf8mb4_general_ci COMMENT = '预订记录表' ROW_FORMAT = Dynamic;

-- ----------------------------
-- Records of reservation
-- ----------------------------

-- ----------------------------
-- Table structure for room
-- ----------------------------
DROP TABLE IF EXISTS `room`;
CREATE TABLE `room`  (
  `room_id` int NOT NULL COMMENT '房间号',
  `room_type` varchar(20) CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci NOT NULL COMMENT '客房类别',
  `area` int NULL DEFAULT NULL COMMENT '面积',
  `price` decimal(10, 2) NOT NULL COMMENT '房价',
  `status` enum('空闲','已预订','已入住','清洁中','维修中') CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci NULL DEFAULT '空闲' COMMENT '房间状态',
  PRIMARY KEY (`room_id`) USING BTREE,
  INDEX `idx_room_status`(`status` ASC) USING BTREE
) ENGINE = InnoDB CHARACTER SET = utf8mb4 COLLATE = utf8mb4_general_ci COMMENT = '客房信息表' ROW_FORMAT = Dynamic;

-- ----------------------------
-- Records of room
-- ----------------------------
INSERT INTO `room` VALUES (101, '单人间', 20, 200.00, '空闲');
INSERT INTO `room` VALUES (102, '标准间', 30, 300.00, '空闲');
INSERT INTO `room` VALUES (103, '大床房', 25, 280.00, '空闲');
INSERT INTO `room` VALUES (104, '套房', 50, 600.00, '空闲');
INSERT INTO `room` VALUES (105, '标准间', 32, 320.00, '空闲');
INSERT INTO `room` VALUES (106, '单人间', 18, 180.00, '空闲');
INSERT INTO `room` VALUES (107, '套房', 300, 2000.00, '空闲');

-- ----------------------------
-- Table structure for room_change
-- ----------------------------
DROP TABLE IF EXISTS `room_change`;
CREATE TABLE `room_change`  (
  `change_id` int NOT NULL AUTO_INCREMENT COMMENT '换房记录编号',
  `old_room_id` int NOT NULL COMMENT '原房间号',
  `new_room_id` int NOT NULL COMMENT '新房间号',
  `cust_id` int NOT NULL COMMENT '客户编号',
  `change_time` datetime NOT NULL COMMENT '换房时间',
  `reason` varchar(100) CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci NULL DEFAULT NULL COMMENT '换房原因',
  PRIMARY KEY (`change_id`) USING BTREE,
  INDEX `idx_change_old_room`(`old_room_id` ASC) USING BTREE,
  INDEX `idx_change_new_room`(`new_room_id` ASC) USING BTREE,
  INDEX `idx_change_cust`(`cust_id` ASC) USING BTREE,
  CONSTRAINT `room_change_ibfk_1` FOREIGN KEY (`old_room_id`) REFERENCES `room` (`room_id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT `room_change_ibfk_2` FOREIGN KEY (`new_room_id`) REFERENCES `room` (`room_id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT `room_change_ibfk_3` FOREIGN KEY (`cust_id`) REFERENCES `customer` (`cust_id`) ON DELETE RESTRICT ON UPDATE RESTRICT
) ENGINE = InnoDB AUTO_INCREMENT = 3 CHARACTER SET = utf8mb4 COLLATE = utf8mb4_general_ci COMMENT = '换房记录表' ROW_FORMAT = Dynamic;

-- ----------------------------
-- Records of room_change
-- ----------------------------

-- ----------------------------
-- Table structure for room_maintenance_clean
-- ----------------------------
DROP TABLE IF EXISTS `room_maintenance_clean`;
CREATE TABLE `room_maintenance_clean`  (
  `record_id` int NOT NULL AUTO_INCREMENT COMMENT '记录编号',
  `room_id` int NOT NULL COMMENT '房间号',
  `record_type` enum('维修','清洁') CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci NOT NULL COMMENT '记录类型',
  `record_time` datetime NOT NULL COMMENT '记录时间',
  `handler` varchar(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci NULL DEFAULT NULL COMMENT '处理人',
  `result` varchar(100) CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci NULL DEFAULT NULL COMMENT '处理结果',
  `remark` text CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci NULL COMMENT '备注',
  PRIMARY KEY (`record_id`) USING BTREE,
  INDEX `handler`(`handler` ASC) USING BTREE,
  INDEX `idx_maint_room`(`room_id` ASC) USING BTREE,
  INDEX `idx_maint_time`(`record_time` ASC) USING BTREE,
  CONSTRAINT `room_maintenance_clean_ibfk_1` FOREIGN KEY (`room_id`) REFERENCES `room` (`room_id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT `room_maintenance_clean_ibfk_2` FOREIGN KEY (`handler`) REFERENCES `users` (`username`) ON DELETE RESTRICT ON UPDATE RESTRICT
) ENGINE = InnoDB AUTO_INCREMENT = 8 CHARACTER SET = utf8mb4 COLLATE = utf8mb4_general_ci COMMENT = '客房维修及清洁记录表' ROW_FORMAT = Dynamic;

-- ----------------------------
-- Records of room_maintenance_clean
-- ----------------------------

-- ----------------------------
-- Table structure for users
-- ----------------------------
DROP TABLE IF EXISTS `users`;
CREATE TABLE `users`  (
  `user_id` int NOT NULL AUTO_INCREMENT COMMENT '用户编号',
  `username` varchar(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci NOT NULL COMMENT '登录名',
  `password` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci NOT NULL COMMENT '密码',
  `role` enum('manager','receptionist') CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci NOT NULL COMMENT '角色',
  `created_at` datetime NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  PRIMARY KEY (`user_id`) USING BTREE,
  UNIQUE INDEX `username`(`username` ASC) USING BTREE
) ENGINE = InnoDB AUTO_INCREMENT = 3 CHARACTER SET = utf8mb4 COLLATE = utf8mb4_general_ci COMMENT = '系统用户表' ROW_FORMAT = Dynamic;

-- ----------------------------
-- Records of users
-- ----------------------------
INSERT INTO `users` VALUES (1, 'manager', '123456', 'manager', '2026-05-27 10:25:16');
INSERT INTO `users` VALUES (2, 'reception', '123456', 'receptionist', '2026-05-27 10:25:16');

-- ----------------------------
-- Triggers structure for table checkin
-- ----------------------------
DROP TRIGGER IF EXISTS `tr_checkin_before_insert`;
delimiter ;;
CREATE TRIGGER `tr_checkin_before_insert` BEFORE INSERT ON `checkin` FOR EACH ROW BEGIN
    DECLARE room_status VARCHAR(20);
    SELECT status INTO room_status FROM room WHERE room_id = NEW.room_id;
    IF room_status NOT IN ('空闲', '已预订') THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = '房间状态不允许入住（需为空闲或已预订）';
    END IF;
    -- 检查经办人是否存在
    IF NEW.operator IS NOT NULL AND NOT EXISTS (SELECT 1 FROM users WHERE username = NEW.operator) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = '经办人不存在';
    END IF;
END
;;
delimiter ;

-- ----------------------------
-- Triggers structure for table checkin
-- ----------------------------
DROP TRIGGER IF EXISTS `tr_checkin_before_update`;
delimiter ;;
CREATE TRIGGER `tr_checkin_before_update` BEFORE UPDATE ON `checkin` FOR EACH ROW BEGIN
    IF OLD.actual_checkout_time IS NULL AND NEW.actual_checkout_time IS NOT NULL THEN
    -- 自动将房间状态设为“清洁中”
        UPDATE room SET status = '清洁中' WHERE room_id = NEW.room_id;
    END IF;
END
;;
delimiter ;

-- ----------------------------
-- Triggers structure for table checkin
-- ----------------------------
DROP TRIGGER IF EXISTS `tr_checkin_after_insert`;
delimiter ;;
CREATE TRIGGER `tr_checkin_after_insert` AFTER INSERT ON `checkin` FOR EACH ROW BEGIN
    UPDATE room SET status = '已入住' WHERE room_id = NEW.room_id;
END
;;
delimiter ;

-- ----------------------------
-- Triggers structure for table checkout
-- ----------------------------
DROP TRIGGER IF EXISTS `tr_checkout_before_insert`;
delimiter ;;
CREATE TRIGGER `tr_checkout_before_insert` BEFORE INSERT ON `checkout` FOR EACH ROW BEGIN
    DECLARE room_price DECIMAL(10,2);
    SELECT price INTO room_price FROM room WHERE room_id = NEW.room_id;
    SET NEW.total_fee = room_price + IFNULL(NEW.extra_fee, 0);
    -- 更新入住记录中的实际退房时间
    UPDATE checkin 
    SET actual_checkout_time = NEW.checkout_time 
    WHERE room_id = NEW.room_id AND cust_id = NEW.cust_id AND actual_checkout_time IS NULL
    ORDER BY checkin_time DESC LIMIT 1;
    -- 更新房间状态为清洁中
    UPDATE room SET status = '清洁中' WHERE room_id = NEW.room_id;
END
;;
delimiter ;

-- ----------------------------
-- Triggers structure for table customer
-- ----------------------------
DROP TRIGGER IF EXISTS `tr_customer_before_insert`;
delimiter ;;
CREATE TRIGGER `tr_customer_before_insert` BEFORE INSERT ON `customer` FOR EACH ROW BEGIN
    IF NEW.name IS NULL OR NEW.name = '' THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = '客户姓名不能为空';
    END IF;
    IF NEW.phone_encrypted IS NULL OR LENGTH(NEW.phone_encrypted) = 0 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = '联系方式不能为空';
    END IF;
END
;;
delimiter ;

-- ----------------------------
-- Triggers structure for table reservation
-- ----------------------------
DROP TRIGGER IF EXISTS `tr_reservation_before_insert`;
delimiter ;;
CREATE TRIGGER `tr_reservation_before_insert` BEFORE INSERT ON `reservation` FOR EACH ROW BEGIN
    DECLARE room_status VARCHAR(20);
    SELECT status INTO room_status FROM room WHERE room_id = NEW.room_id;
    IF room_status != '空闲' THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = '房间不可预订（当前状态不允许）';
    END IF;
  -- 检查同一房间同一天是否已被预订（防止重复预订）
    IF EXISTS (SELECT 1 FROM reservation WHERE room_id = NEW.room_id AND checkin_date = NEW.checkin_date AND status = '已预订') THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = '该房间当天已被预订';
    END IF;
END
;;
delimiter ;

-- ----------------------------
-- Triggers structure for table reservation
-- ----------------------------
DROP TRIGGER IF EXISTS `tr_reservation_after_insert`;
delimiter ;;
CREATE TRIGGER `tr_reservation_after_insert` AFTER INSERT ON `reservation` FOR EACH ROW BEGIN
    UPDATE room SET status = '已预订' WHERE room_id = NEW.room_id;
END
;;
delimiter ;

-- ----------------------------
-- Triggers structure for table reservation
-- ----------------------------
DROP TRIGGER IF EXISTS `tr_reservation_after_update`;
delimiter ;;
CREATE TRIGGER `tr_reservation_after_update` AFTER UPDATE ON `reservation` FOR EACH ROW BEGIN
    IF OLD.status != NEW.status AND NEW.status = '已取消' THEN
        -- 检查房间是否有对应的入住记录（未退房）
        IF NOT EXISTS (SELECT 1 FROM checkin WHERE room_id = NEW.room_id AND actual_checkout_time IS NULL) THEN
            UPDATE room SET status = '空闲' WHERE room_id = NEW.room_id;
        END IF;
    END IF;
END
;;
delimiter ;

-- ----------------------------
-- Triggers structure for table room
-- ----------------------------
DROP TRIGGER IF EXISTS `tr_room_status_change`;
delimiter ;;
CREATE TRIGGER `tr_room_status_change` AFTER UPDATE ON `room` FOR EACH ROW BEGIN
    IF OLD.status != NEW.status THEN
        INSERT INTO operation_log (operator, operation_type, detail)
        VALUES (CURRENT_USER(), '客房状态变更', CONCAT('房间', NEW.room_id, '状态从', OLD.status, '变为', NEW.status));
    END IF;
END
;;
delimiter ;

-- ----------------------------
-- Triggers structure for table room_change
-- ----------------------------
DROP TRIGGER IF EXISTS `tr_room_change_before_insert`;
delimiter ;;
CREATE TRIGGER `tr_room_change_before_insert` BEFORE INSERT ON `room_change` FOR EACH ROW BEGIN
    DECLARE old_status VARCHAR(20);
    DECLARE new_status VARCHAR(20);
    SELECT status INTO old_status FROM room WHERE room_id = NEW.old_room_id;
    SELECT status INTO new_status FROM room WHERE room_id = NEW.new_room_id;
    IF old_status != '已入住' THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = '原房间未入住，不能换房';
    END IF;
    IF new_status != '空闲' THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = '新房间不可用（非空闲）';
    END IF;
END
;;
delimiter ;

-- ----------------------------
-- Triggers structure for table room_change
-- ----------------------------
DROP TRIGGER IF EXISTS `tr_room_change_after_insert`;
delimiter ;;
CREATE TRIGGER `tr_room_change_after_insert` AFTER INSERT ON `room_change` FOR EACH ROW BEGIN
    -- 将原房间设为空闲
    UPDATE room SET status = '空闲' WHERE room_id = NEW.old_room_id;
    -- 将新房间设为已入住
    UPDATE room SET status = '已入住' WHERE room_id = NEW.new_room_id;
END
;;
delimiter ;

-- ----------------------------
-- Triggers structure for table room_maintenance_clean
-- ----------------------------
DROP TRIGGER IF EXISTS `tr_maintenance_before_insert`;
delimiter ;;
CREATE TRIGGER `tr_maintenance_before_insert` BEFORE INSERT ON `room_maintenance_clean` FOR EACH ROW BEGIN
    IF NEW.record_type = '维修' THEN
        UPDATE room SET status = '维修中' WHERE room_id = NEW.room_id;
    ELSEIF NEW.record_type = '清洁' THEN
        UPDATE room SET status = '清洁中' WHERE room_id = NEW.room_id;
    END IF;
END
;;
delimiter ;

-- ----------------------------
-- Triggers structure for table room_maintenance_clean
-- ----------------------------
DROP TRIGGER IF EXISTS `tr_maintenance_after_update`;
delimiter ;;
CREATE TRIGGER `tr_maintenance_after_update` AFTER UPDATE ON `room_maintenance_clean` FOR EACH ROW BEGIN
    -- 判断 result 是否从非完成状态变为完成状态
    IF (OLD.result NOT LIKE '%完成%' OR OLD.result IS NULL) 
       AND (NEW.result LIKE '%完成%') THEN
        -- 将房间状态设为空闲，但需确保房间不在入住或预订状态
        UPDATE room SET status = '空闲' WHERE room_id = NEW.room_id;
    END IF;
END
;;
delimiter ;

SET FOREIGN_KEY_CHECKS = 1;
